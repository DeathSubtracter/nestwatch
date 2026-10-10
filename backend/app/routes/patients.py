"""Maya's local profile and unified timeline."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends

from ..clients.open_wearables import OpenWearablesClient
from ..dependencies import get_date_range, get_open_wearables_client
from ..schemas.patient import Patient
from ..schemas.timeline import PatientTimeline
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
