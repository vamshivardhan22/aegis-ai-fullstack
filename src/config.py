"""Application configuration for Aegis AI."""

from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and .env files."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    AEGIS_ENV: Literal["development", "staging", "production"] = "development"
    AEGIS_DEBUG: bool = False
    AEGIS_DB_URL: str = "sqlite+aiosqlite:///./aegis.db"
    AEGIS_DB_POOL_SIZE: int = 10
    AEGIS_DB_MAX_OVERFLOW: int = 20
    AEGIS_STORAGE_BACKEND: Literal["local", "minio"] = "local"
    AEGIS_LOCAL_STORAGE_PATH: str = "./data"
    AEGIS_MINIO_ENDPOINT: str = "localhost:9000"
    AEGIS_MINIO_ACCESS_KEY: str = "minioadmin"
    AEGIS_MINIO_SECRET_KEY: str = "minioadmin"
    AEGIS_MINIO_BUCKET: str = "aegis-data"
    AEGIS_MINIO_SECURE: bool = False
    AEGIS_REDIS_URL: str = "redis://localhost:6379/0"
    AEGIS_MLFLOW_TRACKING_URI: str = "http://localhost:5000"
    AEGIS_MLFLOW_EXPERIMENT_NAME: str = "aegis-default"
    AEGIS_OLLAMA_URL: str = "http://localhost:11434"
    AEGIS_LLM_MODEL: str = "llama3.1"
    AEGIS_EMBEDDING_MODEL: str = "nomic-embed-text"
    AEGIS_QDRANT_URL: str = "http://localhost:6333"
    AEGIS_QDRANT_COLLECTION: str = "aegis-knowledge"
    AEGIS_LLM_FALLBACK: Optional[str] = None
    AEGIS_LLM_TIMEOUT: int = 120
    AEGIS_SECRET_KEY: str = Field(default="change-me-in-production")
    AEGIS_JWT_ALGORITHM: str = "HS256"
    AEGIS_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    AEGIS_MAX_RETRIES: int = 3
    AEGIS_RETRY_DELAY_SECONDS: int = 5
    AEGIS_HUMAN_APPROVAL_RISK_THRESHOLD: float = 0.7

    @property
    def is_postgres(self) -> bool:
        """Return True when the configured database is PostgreSQL."""

        return self.AEGIS_DB_URL.startswith(("postgresql", "postgres"))

    @property
    def is_sqlite(self) -> bool:
        """Return True when the configured database is SQLite."""

        return self.AEGIS_DB_URL.startswith("sqlite")

    @property
    def is_async_db(self) -> bool:
        """Return True when the database URL contains an async driver."""

        return "+aiosqlite" in self.AEGIS_DB_URL or "+asyncpg" in self.AEGIS_DB_URL


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
