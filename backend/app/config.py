"""Environment configuration for the Nestwatch backend."""

from pathlib import Path

from pydantic import AnyHttpUrl, SecretStr
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
