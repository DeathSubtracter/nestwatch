"""A narrowly defined synthetic BP measurement event, never a diagnosis."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class BPReviewThresholds(BaseModel):
    systolic_mm_hg: float = Field(gt=0, allow_inf_nan=False)
    diastolic_mm_hg: float = Field(gt=0, allow_inf_nan=False)
    comparison: Literal[">="] = ">="
    combine: Literal["or"] = "or"


class BPFeatureContribution(BaseModel):
    feature: str
    value: float = Field(allow_inf_nan=False)
    standardized_log_odds_contribution: float = Field(allow_inf_nan=False)


class BPClassificationMetrics(BaseModel):
    accuracy: float = Field(ge=0, le=1, allow_inf_nan=False)
    classification_threshold: Literal[0.5] = 0.5
    precision: float | None = Field(ge=0, le=1, allow_inf_nan=False)
    recall: float | None = Field(ge=0, le=1, allow_inf_nan=False)
    specificity: float | None = Field(ge=0, le=1, allow_inf_nan=False)
    f1: float | None = Field(ge=0, le=1, allow_inf_nan=False)
    brier_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    log_loss: float = Field(ge=0, allow_inf_nan=False)
    roc_auc: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    roc_auc_unavailable_reason: str | None = None
    true_positives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    true_negatives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    unavailable_reasons: list[str] = Field(default_factory=list)


class SyntheticBPHoldoutMetrics(BPClassificationMetrics):
    scope: Literal["synthetic_data_only"] = "synthetic_data_only"
    split_method: Literal["chronological_80_20_purged_7d"] = "chronological_80_20_purged_7d"
    evaluation_method: Literal["non_overlapping_7d_event_windows"] = "non_overlapping_7d_event_windows"
    no_event_baseline_accuracy: float = Field(ge=0, le=1, allow_inf_nan=False)
    constant_no_event_baseline: BPClassificationMetrics
    training_start: datetime
    training_end: datetime
    holdout_start: datetime
    holdout_end: datetime
    training_measurements: int
    training_windows: int
    training_positive_events: int
    training_negative_events: int
    holdout_measurements: int
    evaluated_windows: int
    evaluated_bp_measurements: int
    holdout_positive_events: int
    holdout_negative_events: int


class BPForecast(BaseModel):
    patient_id: Literal["maya"] = "maya"
    forecast_origin: datetime | None
    last_observation_timestamp: datetime | None
    horizon_days: Literal[7] = 7
    event_definition: str
    event_window_end: datetime | None
    model_type: Literal["logistic_regression"] = "logistic_regression"
    probability: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    status: Literal["forecast_available", "insufficient_data"]
    thresholds: BPReviewThresholds
    synthetic: Literal[True] = True
    validated: Literal[False] = False
    prototype: Literal[True] = True
    reasons: list[str] = Field(default_factory=list)
    feature_values: dict[str, float] = Field(default_factory=dict)
    main_contributing_features: list[BPFeatureContribution] = Field(default_factory=list)
    holdout_metrics: SyntheticBPHoldoutMetrics | None = None
