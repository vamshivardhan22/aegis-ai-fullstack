"""Tests for fail-closed production configuration validation."""
import pytest
from pydantic import ValidationError

from src.config import Settings


def test_production_rejects_development_defaults() -> None:
    with pytest.raises(ValidationError, match="Unsafe production configuration"):
        Settings(AEGIS_ENV="production")


def test_production_accepts_explicit_secure_configuration() -> None:
    settings = Settings(
        AEGIS_ENV="production",
        AEGIS_DEBUG=False,
        AEGIS_SECRET_KEY="s" * 48,
        AEGIS_DB_URL="postgresql+asyncpg://aegis:strong-password@db.internal:5432/aegis",
        AEGIS_STORAGE_BACKEND="minio",
        AEGIS_MINIO_ACCESS_KEY="aegis-service",
        AEGIS_MINIO_SECRET_KEY="not-a-default-secret",
        AEGIS_LLM_PROVIDER="openai",
        AEGIS_OPENAI_API_KEY="sk-test-config-validation-only",
        AEGIS_CORS_ORIGINS="https://aegis.company.com",
        AEGIS_CORS_ORIGIN_REGEX=None,
    )
    assert settings.AEGIS_ENV == "production"
    assert settings.is_postgres
