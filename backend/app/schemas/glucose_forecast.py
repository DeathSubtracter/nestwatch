"""Synthetic research forecasts and their chronological evaluation metadata."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GlucoseForecastPoint(BaseModel):
    timestamp: datetime
    glucose_mg_dl: float = Field(allow_inf_nan=False)


class SyntheticHoldoutMetrics(BaseModel):
    scope: Literal["synthetic_data_only"] = "synthetic_data_only"
    split_method: Literal["chronological_80_20"] = "chronological_80_20"
    evaluation_method: Literal["non_overlapping_24h_forecasts"] = "non_overlapping_24h_forecasts"
    mae_mg_dl: float = Field(ge=0, allow_inf_nan=False)
    rmse_mg_dl: float = Field(ge=0, allow_inf_nan=False)
    training_start: datetime
    training_end: datetime
    holdout_start: datetime
    holdout_end: datetime
    training_samples: int
    training_windows: int
    holdout_samples: int
    evaluation_origins: int
    evaluated_points: int


class GlucoseForecast(BaseModel):
    patient_id: Literal["maya"] = "maya"
    forecast_origin: datetime
    last_observation_timestamp: datetime
    horizon_hours: Literal[24] = 24
    cadence_minutes: Literal[5] = 5
    model_type: Literal["ridge_regression"] = "ridge_regression"
    forecast_strategy: Literal["direct_multi_output"] = "direct_multi_output"
    prototype: Literal[True] = True
    validated: Literal[False] = False
    synthetic: Literal[True] = True
    unit: Literal["mg/dL"] = "mg/dL"
    features: list[str]
    forecast_points: list[GlucoseForecastPoint] = Field(min_length=288, max_length=288)
    holdout_metrics: SyntheticHoldoutMetrics
