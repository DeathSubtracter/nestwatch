"""Stable dashboard sections and explicit availability for frontend rendering."""

from typing import Literal

from pydantic import BaseModel, Field

from .bp_forecast import BPForecast
from .glucose_forecast import GlucoseForecast
from .observed_change import ComparisonWindow, ObservedChange
from .patient import Patient
from .pattern_status import PatternStatus
from .timeline import PatientTimeline, TimelineEntry


class DashboardSectionQuality(BaseModel):
    status: Literal["available", "partial", "insufficient_data", "unavailable"]
    reasons: list[str] = Field(default_factory=list)
    metric_reasons: dict[str, list[str]] = Field(default_factory=dict)


class LatestMeasurement(BaseModel):
    metric_type: str
    metric_definition: str
    status: Literal["available", "missing", "stale", "unavailable"]
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: str | None = None
    timestamp: str | None = None
    provider: str | None = None
    source: str | None = None
    device: str | None = None
    device_type: str | None = None
    reasons: list[str] = Field(default_factory=list)


class DashboardSleepSummary(BaseModel):
    window: ComparisonWindow
    status: Literal["available", "missing", "stale", "unavailable"]
    latest_session: TimelineEntry | None
    session_count: int | None
    reasons: list[str] = Field(default_factory=list)


class DashboardDataQuality(BaseModel):
    status: Literal["complete", "partial", "insufficient_data"]
    max_staleness_days: int
    freshness_relative_to: Literal["section_window_end"] = "section_window_end"
    missing_measurements: list[str]
    stale_measurements: list[str]
    sections: dict[str, DashboardSectionQuality]
    unavailable_sections: dict[str, list[str]]


class PatientDashboard(BaseModel):
    synthetic: Literal[True] = True
    prototype: Literal[True] = True
    validated: Literal[False] = False
    patient: Patient
    latest_measurements: dict[str, LatestMeasurement]
    timeline: PatientTimeline
    observed_change: ObservedChange | None
    pattern_status: PatternStatus | None
    glucose_forecast: GlucoseForecast | None
    bp_forecast: BPForecast | None
    sleep_summary: DashboardSleepSummary
    data_quality: DashboardDataQuality
