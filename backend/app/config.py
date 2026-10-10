"""Environment configuration for the Nestwatch backend."""

from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    open_wearables_base_url: AnyHttpUrl = "http://localhost:8000"
    open_wearables_api_key: SecretStr = SecretStr("")
    open_wearables_user_id: str = ""
    nestwatch_patient_id: str = "maya"

    # Data sufficiency rules, not clinical thresholds.
    observed_change_min_samples: int = Field(default=3, ge=2)
    observed_change_max_staleness_days: int = Field(default=2, ge=0)

    # Editable synthetic-event review values; these are not diagnostic rules.
    bp_review_systolic_threshold: float = Field(default=140.0, gt=0, allow_inf_nan=False)
    bp_review_diastolic_threshold: float = Field(default=90.0, gt=0, allow_inf_nan=False)

    # Multisignal hackathon fixtures: relative engineering rules, not clinical cutoffs.
    pattern_normalized_change_threshold: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    pattern_relative_scale_floor: float = Field(default=0.05, gt=0, le=1, allow_inf_nan=False)
    pattern_min_days_per_window: int = Field(default=3, ge=1)
    pattern_min_samples_per_day: int = Field(default=1, ge=1)
    pattern_persistence_days: int = Field(default=3, ge=2)
    pattern_review_min_groups: int = Field(default=3, ge=2, le=5)
    pattern_min_available_groups: int = Field(default=3, ge=2, le=5)
    pattern_required_signals: list[Literal[
        "blood_glucose", "blood_pressure_systolic", "blood_pressure_diastolic",
        "resting_heart_rate", "heart_rate_variability_sdnn", "sleep_duration", "sleep_efficiency",
    ]] = Field(default_factory=lambda: [
        "blood_glucose", "blood_pressure_systolic", "blood_pressure_diastolic",
        "resting_heart_rate", "heart_rate_variability_sdnn",
    ], min_length=1)
