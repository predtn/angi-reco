from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_KEY_MIN_LENGTH = 32


class Settings(BaseSettings):
    """Read from environment variables, then from `.env` (local only, never committed)."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    environment: Literal["development", "test", "production"] = "development"
    # postgresql+psycopg://angi_reco:<password>@<host>:5432/angi (role angi_reco owns schema
    # recommendation). Alembic uses the same URL with the sync driver.
    database_url: str
    # Shared secret with the backend (Recommendation:ApiKey), sent as header X-Api-Key.
    reco_api_key: SecretStr
    # Key of the LLM that generates dish vectors; required once dish upsert exists.
    llm_api_key: SecretStr | None = None
    log_level: str = "INFO"

    @field_validator("reco_api_key")
    @classmethod
    def _check_api_key_length(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < API_KEY_MIN_LENGTH:
            raise ValueError(f"must be at least {API_KEY_MIN_LENGTH} characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
