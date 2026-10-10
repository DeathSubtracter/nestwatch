"""Temporary endpoints for checking the Open Wearables integration."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from ..clients.open_wearables import OpenWearablesClient
from ..dependencies import get_date_range, get_open_wearables_client

router = APIRouter(prefix="/debug/open-wearables", tags=["debug"])


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
