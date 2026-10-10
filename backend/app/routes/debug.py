"""Temporary endpoints for checking the Open Wearables integration."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..clients.open_wearables import OpenWearablesClient

router = APIRouter(prefix="/debug/open-wearables", tags=["debug"])


def get_open_wearables_client(request: Request) -> OpenWearablesClient:
    return request.app.state.open_wearables


def get_date_range(start_date: date, end_date: date) -> tuple[date, date]:
    if start_date > end_date:
        raise HTTPException(422, "start_date must be on or before end_date")
    return start_date, end_date


@router.get("/timeseries")
async def timeseries(
    dates: Annotated[tuple[date, date], Depends(get_date_range)],
    client: Annotated[OpenWearablesClient, Depends(get_open_wearables_client)],
    types: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    data = await client.get_timeseries(*dates, types=types)
    return {"data": data, "count": len(data)}


@router.get("/sleep")
async def sleep(
    dates: Annotated[tuple[date, date], Depends(get_date_range)],
    client: Annotated[OpenWearablesClient, Depends(get_open_wearables_client)],
) -> dict[str, Any]:
    data = await client.get_sleep(*dates)
    return {"data": data, "count": len(data)}
