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

    # The Vite dev server and the deployed frontend run on a different
    # origin than the API, so the browser needs CORS to fetch /api/*.
    # Override via CORS_ORIGINS="https://foo.vercel.app,https://bar.com"
    # once the frontend is actually deployed (Phase 9).
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
