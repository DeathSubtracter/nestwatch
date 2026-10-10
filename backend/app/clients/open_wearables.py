"""Async access to normalized Open Wearables records."""

from datetime import date
from typing import Any
from urllib.parse import quote

import httpx

from ..config import Settings


class OpenWearablesError(Exception):
    """A safe error message and the corresponding Nestwatch HTTP status."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class OpenWearablesClient:
    """Fetch complete date ranges using a caller-managed HTTP client."""

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http_client

    async def get_timeseries(
        self, start_date: date, end_date: date, types: list[str] | None = None
    ) -> list[dict[str, Any]]:
        self._validate_dates(start_date, end_date)
        params = [
            ("start_time", start_date.isoformat()),
            ("end_time", end_date.isoformat()),
            ("resolution", "raw"),
        ]
        params.extend(("types", metric) for metric in types or [])
        return await self._fetch_all("timeseries", params)

    async def get_sleep(
        self, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        self._validate_dates(start_date, end_date)
        return await self._fetch_all(
            "events/sleep",
            [("start_date", start_date.isoformat()), ("end_date", end_date.isoformat())],
        )

    @staticmethod
    def _validate_dates(start_date: date, end_date: date) -> None:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")

    async def _fetch_all(
        self, resource: str, params: list[tuple[str, str]]
    ) -> list[dict[str, Any]]:
        user_id = self._settings.open_wearables_user_id
        api_key = self._settings.open_wearables_api_key.get_secret_value()
        if not user_id.strip() or not api_key.strip():
            raise OpenWearablesError(
                "Configure OPEN_WEARABLES_API_KEY and OPEN_WEARABLES_USER_ID", 503
            )

        base_url = str(self._settings.open_wearables_base_url).rstrip("/")
        url = f"{base_url}/api/v1/users/{quote(user_id, safe='')}/{resource}"
        headers = {"X-Open-Wearables-API-Key": api_key}
        params = [*params, ("limit", "1000")]
        records: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while True:
            page_params = [*params, ("cursor", cursor)] if cursor else params
            try:
                response = await self._http.get(url, headers=headers, params=page_params)
            except httpx.TimeoutException as exc:
                raise OpenWearablesError("Open Wearables request timed out", 504) from exc
            except httpx.RequestError as exc:
                raise OpenWearablesError("Open Wearables is unavailable", 503) from exc

            if not response.is_success:
                raise OpenWearablesError(
                    f"Open Wearables returned HTTP {response.status_code}"
                )
            try:
                page = response.json()
            except ValueError as exc:
                raise OpenWearablesError("Open Wearables returned invalid JSON") from exc

            if not isinstance(page, dict):
                raise OpenWearablesError("Open Wearables returned an invalid page")
            data = page.get("data")
            pagination = page.get("pagination")
            if (
                not isinstance(data, list)
                or any(not isinstance(record, dict) for record in data)
                or not isinstance(pagination, dict)
                or not isinstance(pagination.get("has_more"), bool)
            ):
                raise OpenWearablesError("Open Wearables returned an invalid page")

            # Keep complete upstream records, including nested source metadata.
            records.extend(data)
            if not pagination["has_more"]:
                return records
            cursor = pagination.get("next_cursor")
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise OpenWearablesError("Open Wearables returned invalid pagination")
            seen_cursors.add(cursor)
