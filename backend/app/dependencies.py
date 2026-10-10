"""Shared route dependencies."""

from datetime import date

from fastapi import HTTPException, Request

from .clients.open_wearables import OpenWearablesClient


def get_open_wearables_client(request: Request) -> OpenWearablesClient:
    return request.app.state.open_wearables


def get_date_range(start_date: date, end_date: date) -> tuple[date, date]:
    if start_date > end_date:
        raise HTTPException(422, "start_date must be on or before end_date")
    return start_date, end_date
