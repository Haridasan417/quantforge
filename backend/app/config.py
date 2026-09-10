"""Central settings, read from environment / .env.

Alembic's env.py imports DATABASE_URL from here too, so the DB URL is
defined in exactly one place.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/quantforge"
    redis_url: str = "redis://localhost:6379"
    smartapi_key: str = ""
    smartapi_client_id: str = ""


settings = Settings()
