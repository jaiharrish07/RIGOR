"""Application settings loaded from environment variables.

Uses pydantic-settings to validate types at startup — a missing or
malformed env var fails immediately rather than crashing mid-request.

Usage:
    from app.config import settings
    print(settings.database_url)
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All backend configuration in one typed object."""

    # --- Database ---
    database_url: str = Field(
        default="postgresql+psycopg://rigor:rigor@localhost:5433/rigor",
        description="SQLAlchemy connection string for Postgres.",
    )
    test_database_url: str = Field(
        default="postgresql+psycopg://rigor:rigor@localhost:5433/rigor_test",
        description="Test database connection string. Used only by pytest.",
    )

    # --- GROBID ---
    grobid_url: str = Field(
        default="http://localhost:8070",
        description="Base URL of the running GROBID service.",
    )

    # --- LLM (Groq primary) ---
    groq_api_key: str = Field(
        default="",
        description="API key for Groq LLM service.",
    )
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Groq model identifier.",
    )

    # --- LLM (OpenRouter fallback) ---
    openrouter_api_key: str = Field(
        default="",
        description="API key for OpenRouter LLM fallback service.",
    )
    openrouter_model: str = Field(
        default="meta-llama/llama-4-maverick:free",
        description="OpenRouter model identifier (fallback).",
    )

    # --- App ---
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")
    max_upload_size_mb: int = Field(
        default=20,
        description="Maximum PDF upload size in megabytes.",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def max_upload_size_bytes(self) -> int:
        """Convenience: upload cap expressed in bytes."""
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton.

    lru_cache means the .env file is read exactly once per process.
    Import ``settings`` (below) instead of calling this directly in most code.
    """
    return Settings()


# Import this everywhere: from app.config import settings
settings = get_settings()