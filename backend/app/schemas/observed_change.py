"""Descriptive window comparisons and explicit data availability."""

from datetime import date
from typing import Literal

from pydantic import BaseModel


class ComparisonWindow(BaseModel):
    start_date: date
    end_date: date


class ComparisonPolicy(BaseModel):
    aggregation: Literal["sample_mean"] = "sample_mean"
    minimum_samples_per_window: int
    max_staleness_days: int
    freshness_relative_to: Literal["each_window_end"] = "each_window_end"


class SourceProvenance(BaseModel):
    provider: str | None
    source: str | None
    device: str | None
    device_type: str | None
    sample_count: int


class MetricComparison(BaseModel):
    metric_type: str
    metric_name: str
    metric_definition: str
    unit: str | None
    available_units: list[str]
    reference_units: list[str]
    recent_units: list[str]
    reference_sample_count: int
    recent_sample_count: int
    reference_mean: float | None
    recent_mean: float | None
    absolute_change: float | None
    percent_change: float | None
    percent_change_unavailable_reason: str | None
    reference_latest_timestamp: str | None
    recent_latest_timestamp: str | None
    reference_provenance: list[SourceProvenance]
    recent_provenance: list[SourceProvenance]
    provenance_changed: bool
    enough_data: bool
    status: Literal["compared", "insufficient_data"]
    reasons: list[str]


class ObservedChange(BaseModel):
    patient_id: str
    synthetic: bool
    analysis_type: Literal["observed_change"] = "observed_change"
    timezone: Literal["UTC"] = "UTC"
    reference_window: ComparisonWindow
    recent_window: ComparisonWindow
    policy: ComparisonPolicy
    metrics: list[MetricComparison]
