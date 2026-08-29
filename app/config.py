"""Application settings, loaded from the environment.

Minimal by design: this module exists because every other module needs
`database_url`, and the committed file was empty. It covers only the keys
already present in `.env.example` plus `test_database_url`.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8-sig", extra="ignore"
    )

    # --- Database ---
    database_url: str = "postgresql+psycopg://rigor:rigor@localhost:5432/rigor"
    test_database_url: str = "postgresql+psycopg://rigor:rigor@localhost:5432/rigor_test"

    # --- GROBID ---
    grobid_url: str = "http://localhost:8070"

    # --- LLM (Groq primary) ---
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # --- LLM (OpenRouter fallback) ---
    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-4-maverick:free"

    # --- App settings ---
    app_env: str = "development"
    log_level: str = "INFO"
    max_upload_size_mb: int = 20


settings = Settings()