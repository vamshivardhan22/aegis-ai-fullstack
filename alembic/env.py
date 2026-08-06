"""Alembic migration environment."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.config import get_settings
from src.database.base import Base
from src.database import models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_url(url: str) -> str:
    """Convert async SQLAlchemy URLs to sync URLs for Alembic."""

    return url.replace("+aiosqlite", "").replace("+asyncpg", "")


def run_migrations_offline() -> None:
    """Run migrations without a live database connection."""

    url = _sync_url(get_settings().AEGIS_DB_URL)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live database connection."""

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _sync_url(get_settings().AEGIS_DB_URL)
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
