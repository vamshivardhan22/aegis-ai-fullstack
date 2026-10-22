"""Application configuration for Aegis AI."""

from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and .env files."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    AEGIS_ENV: Literal["development", "staging", "production"] = "development"
    AEGIS_DEBUG: bool = False
    AEGIS_DB_URL: str = "sqlite+aiosqlite:///./aegis.db"
    AEGIS_DB_POOL_SIZE: int = 10
    AEGIS_DB_MAX_OVERFLOW: int = 20
    AEGIS_STORAGE_BACKEND: Literal["local", "minio", "supabase"] = "local"
    AEGIS_LOCAL_STORAGE_PATH: str = "./data"
    AEGIS_MINIO_ENDPOINT: str = "localhost:9000"
    AEGIS_MINIO_ACCESS_KEY: str = "minioadmin"
    AEGIS_MINIO_SECRET_KEY: str = "minioadmin"
    AEGIS_MINIO_BUCKET: str = "aegis-data"
    AEGIS_MINIO_SECURE: bool = False
    AEGIS_SUPABASE_URL: Optional[str] = None
    AEGIS_SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None
    AEGIS_SUPABASE_BUCKET: str = "aegis-data"
    AEGIS_SUPABASE_PUBLIC_URLS: bool = False
    AEGIS_REDIS_URL: str = "redis://localhost:6379/0"
    AEGIS_MLFLOW_TRACKING_URI: str = "http://localhost:5000"
    AEGIS_MLFLOW_EXPERIMENT_NAME: str = "aegis-default"
    AEGIS_LLM_PROVIDER: Literal["openai", "anthropic", "google"] = "openai"
    AEGIS_LLM_MODEL: str = "gpt-4o-mini"
    AEGIS_LLM_TEMPERATURE: float = 0.2
    AEGIS_LLM_TIMEOUT: int = 120
    AEGIS_OLLAMA_URL: str = "http://localhost:11434"
    AEGIS_OPENAI_API_KEY: Optional[str] = None
    AEGIS_ANTHROPIC_API_KEY: Optional[str] = None
    AEGIS_GOOGLE_API_KEY: Optional[str] = None
    AEGIS_EMBEDDING_PROVIDER: Literal["openai"] = "openai"
    AEGIS_EMBEDDING_MODEL: str = "text-embedding-3-small"
    AEGIS_QDRANT_URL: str = "http://localhost:6333"
    AEGIS_QDRANT_API_KEY: Optional[str] = None
    AEGIS_QDRANT_COLLECTION: str = "aegis-knowledge"
    AEGIS_LLM_FALLBACK: Optional[str] = None
    AEGIS_SECRET_KEY: str = Field(default="change-me-in-production")
    AEGIS_JWT_ALGORITHM: str = "HS256"
    AEGIS_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    AEGIS_CORS_ORIGINS: str = (
        "http://localhost:5173,"
        "http://localhost:5174,"
        "http://127.0.0.1:5173,"
        "http://127.0.0.1:5174,"
        "http://localhost:3000"
    )
    AEGIS_CORS_ORIGIN_REGEX: Optional[str] = r"https://.*[.]app[.]github[.]dev"
    AEGIS_MAX_RETRIES: int = 3
    AEGIS_RETRY_DELAY_SECONDS: int = 5
    AEGIS_HUMAN_APPROVAL_RISK_THRESHOLD: float = 0.7

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """Refuse insecure or ephemeral defaults when explicitly running in production."""
        if self.AEGIS_ENV != "production":
            return self
        problems: list[str] = []
        if self.AEGIS_SECRET_KEY == "change-me-in-production" or len(self.AEGIS_SECRET_KEY) < 32:
            problems.append("AEGIS_SECRET_KEY must be a unique secret of at least 32 characters")
        if self.AEGIS_DEBUG:
            problems.append("AEGIS_DEBUG must be false in production")
        if not self.is_postgres:
            problems.append("AEGIS_DB_URL must use PostgreSQL in production")
        if self.AEGIS_STORAGE_BACKEND == "local":
            problems.append("AEGIS_STORAGE_BACKEND must use durable shared storage in production")
        if self.AEGIS_CORS_ORIGIN_REGEX:
            problems.append("AEGIS_CORS_ORIGIN_REGEX must be unset in production")
        if any("localhost" in origin or "127.0.0.1" in origin for origin in self.cors_origins):
            problems.append("AEGIS_CORS_ORIGINS must not include localhost in production")
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self

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

    @property
    def cors_origins(self) -> list[str]:
        """Return configured CORS origins as a normalized list."""

        return [origin.strip() for origin in self.AEGIS_CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
