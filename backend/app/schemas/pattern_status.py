"""Transparent multisignal rules and data coverage, without disease scoring."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .observed_change import ComparisonWindow, MetricComparison


class PatternPolicy(BaseModel):
    normalized_change_threshold: float
    relative_scale_floor: float
    minimum_samples_per_window: int
    minimum_days_per_window: int
    minimum_samples_per_day: int
    persistence_days: int
    review_min_groups: int
    minimum_available_groups: int
    max_staleness_days: int
    required_signals: list[str]


class DailyPatternChange(BaseModel):
    date: date
    sample_count: int
    mean: float | None
    normalized_change: float | None
    directional_normalized_change: float | None
    qualifying: bool
    reasons: list[str] = Field(default_factory=list)


class SignalPersistence(BaseModel):
    reference_observed_days: list[date]
    recent_observed_days: list[date]
    qualifying_recent_days: list[date]
    longest_consecutive_days: int
    latest_consecutive_days: int
    required_consecutive_days: int
    last_qualifying_date: date | None
    meets_persistence: bool
    daily_changes: list[DailyPatternChange]


class PatternSignal(BaseModel):
    metric_type: str
    metric_name: str
    group: str
    role: Literal["primary", "context"]
    direction: Literal["increase", "decrease", "either"]
    comparison: MetricComparison
    reference_std: float | None
    normalization_scale: float | None
    normalized_change: float | None
    directional_normalized_change: float | None
    contribution: float | None
    changed: bool | None
    contributing: bool
    usable: bool
    rejected_reference_samples: int
    rejected_recent_samples: int
    persistence: SignalPersistence
    reasons: list[str]


class ConcurrentPatternDay(BaseModel):
    date: date
    groups: list[str]


class PatternDataQuality(BaseModel):
    coverage: Literal["complete", "partial", "insufficient"]
    available_primary_signals: list[str]
    unavailable_primary_signals: list[str]
    missing_required_signals: list[str]
    available_groups: list[str]
    unavailable_context_signals: list[str]
    reasons_by_signal: dict[str, list[str]]
    rejected_sleep_values: int


class PatternStatus(BaseModel):
    patient_id: str
    synthetic: bool
    validated: Literal[False] = False
    prototype: Literal[True] = True
    status: Literal["normal", "watch", "change_to_review", "insufficient_data"]
    timezone: Literal["UTC"] = "UTC"
    reference_window: ComparisonWindow
    recent_window: ComparisonWindow
    policy: PatternPolicy
    contributing_signals: list[str]
    non_contributing_signals: list[str]
    signals: list[PatternSignal]
    concurrent_days: list[ConcurrentPatternDay]
    longest_concurrent_days: int
    latest_concurrent_days: int
    reasons: list[str]
    explanation: str
    data_quality: PatternDataQuality
