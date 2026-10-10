"""Consistent fields for frontend timeline rendering."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from .patient import Patient


class TimelineEntry(BaseModel):
    timestamp: str
    kind: Literal["measurement", "sleep", "context", "medication", "symptom"]
    origin: Literal["open_wearables", "nestwatch"]
    metric_type: str
    metric_definition: str
    value: Any
    unit: str | None = None
    provider: str | None = None
    source: str | None = None
    device: str | None = None
    device_type: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class PatientTimeline(BaseModel):
    patient_id: str
    synthetic: bool
    start_date: date
    end_date: date
    timezone: Literal["UTC"] = "UTC"
    patient_context: Patient
    entries: list[TimelineEntry]
    count: int
