"""Maya's local profile and unified timeline."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from ..clients.open_wearables import OpenWearablesClient
from ..dependencies import get_date_range, get_open_wearables_client
from ..schemas.bp_forecast import BPForecast
from ..schemas.glucose_forecast import GlucoseForecast
from ..schemas.observed_change import ObservedChange
from ..schemas.patient import Patient
from ..schemas.pattern_status import PatternStatus
from ..schemas.timeline import PatientTimeline
from ..services.bp_forecast import BPForecastError, get_bp_forecast
from ..services.glucose_forecast import GlucoseForecastError, get_glucose_forecast
from ..services.observed_change import build_observed_change, validate_windows
from ..services.pattern_status import build_pattern_status
from ..services.timeline import build_timeline, load_maya

router = APIRouter(prefix="/patients/maya", tags=["patients"])


@router.get("", response_model=Patient)
def profile() -> Patient:
    return load_maya()


@router.get("/timeline", response_model=PatientTimeline)
async def timeline(
    dates: Annotated[tuple[date, date], Depends(get_date_range)],
    client: Annotated[OpenWearablesClient, Depends(get_open_wearables_client)],
) -> PatientTimeline:
    return await build_timeline(load_maya(), client, *dates)


@router.get("/observed-change", response_model=ObservedChange)
async def observed_change(
    request: Request,
    reference_start: date,
    reference_end: date,
    recent_start: date,
    recent_end: date,
    client: Annotated[OpenWearablesClient, Depends(get_open_wearables_client)],
) -> ObservedChange:
    try:
        validate_windows(reference_start, reference_end, recent_start, recent_end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await build_observed_change(
        load_maya(), client, request.app.state.settings,
        reference_start, reference_end, recent_start, recent_end,
    )


@router.get("/pattern-status", response_model=PatternStatus)
async def pattern_status(
    request: Request,
    reference_start: date,
    reference_end: date,
    recent_start: date,
    recent_end: date,
    client: Annotated[OpenWearablesClient, Depends(get_open_wearables_client)],
) -> PatternStatus:
    try:
        validate_windows(reference_start, reference_end, recent_start, recent_end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await build_pattern_status(
        load_maya(), client, request.app.state.settings,
        reference_start, reference_end, recent_start, recent_end,
    )


@router.get("/forecast/glucose", response_model=GlucoseForecast)
def glucose_forecast() -> GlucoseForecast:
    try:
        return get_glucose_forecast()
    except GlucoseForecastError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/forecast/bp", response_model=BPForecast)
def bp_forecast(request: Request) -> BPForecast:
    settings = request.app.state.settings
    try:
        return get_bp_forecast(settings.bp_review_systolic_threshold, settings.bp_review_diastolic_threshold)
    except BPForecastError as exc:
        raise HTTPException(503, str(exc)) from exc
