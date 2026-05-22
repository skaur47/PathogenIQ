"""
Alembic migration environment for async SQLAlchemy.

Why is this file more complex than a typical Alembic setup?
  Standard Alembic uses synchronous database connections.
  PathogenIQ uses asyncpg, which is async-only.
  Alembic's own migration runner is synchronous, so we need to bridge the gap
  using asyncio.run() and connection.run_sync().

The pattern:
  1. Create an async engine (same as the app uses)
  2. Acquire an async connection
  3. Call connection.run_sync(do_run_migrations) — this runs the synchronous
     Alembic context inside the async connection
  4. Dispose the engine

Important: Alembic migrations run as a separate process (the `alembic` CLI),
not inside the FastAPI app. They should be run before starting the app:
  docker compose run --rm api alembic upgrade head
"""

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Add the /app directory to sys.path so `from app.xxx import` works
# when running alembic from the services/api directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from app.config import get_settings
from app.db.base import Base

# Import ALL models so Alembic can see them in Base.metadata.
# If you add a new model and forget to import it here, Alembic won't
# know about it and won't generate the migration.
import app.db.models  # noqa: F401 — side effect: registers models with Base

config = context.config
settings = get_settings()

# Override the sqlalchemy.url from alembic.ini with our pydantic Settings value.
# This ensures the DB URL comes from environment variables, not a hardcoded ini file.
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata object Alembic uses to detect schema differences
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode — generates SQL without connecting to DB.

    Useful when you want to review the SQL before running it, or when you're
    deploying to a managed DB where your CI doesn't have direct access.

    Usage: alembic upgrade head --sql > migration.sql
    Then review migration.sql and run it manually against production.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,      # detect column type changes
        compare_server_default=True,  # detect server default changes
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """
    The actual migration runner — called inside an async connection via run_sync.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Create an async engine, connect, and run migrations synchronously via run_sync.
    NullPool is used here (instead of the app's connection pool) because
    migrations are a one-shot operation — no need to maintain persistent connections.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online mode — runs the async migration in a sync context."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
