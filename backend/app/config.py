"""Environment configuration for the Nestwatch backend."""

from pathlib import Path

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
