"""
Test fixtures shared across all test files.

Testing architecture:
─────────────────────
We have two categories of tests:

1. Unit / fast tests (this file):
   - Use SQLite in-memory database (no Docker required)
   - Override FastAPI dependencies to inject test DB session
   - Run in ~seconds
   - Catch logic errors, endpoint contracts, response shapes

2. Integration tests (Phase 2, tests/integration/):
   - Require a real PostgreSQL instance (pytest-postgresql or testcontainers)
   - Test migrations, Alembic, and PostgreSQL-specific features
   - Run as part of CI after Docker Compose is up

Why SQLite for unit tests?
  - Zero setup: no Docker, no network, no cleanup
  - In-memory: each test gets a pristine DB, no state leakage between tests
  - Fast: table creation takes microseconds

Limitation: SQLite doesn't support PostgreSQL-specific features
(JSONB, UUID primary keys, partial indexes, etc.). Our models use these.
For unit tests we avoid testing those features directly; integration tests
cover them on real PostgreSQL.

Fixture scopes:
  - session scope: created once per pytest session (expensive setup)
  - function scope: created fresh for each test (default — safest)
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app

# ── Test database ─────────────────────────────────────────────────────────────
# aiosqlite provides an async interface to SQLite
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """
    Create a fresh in-memory SQLite engine and schema for each test.

    StaticPool: SQLite in-memory databases are connection-local by default —
    a second connection would see an empty database. StaticPool forces all
    connections to share the same in-memory database within a test.

    check_same_thread=False: required for SQLite when using asyncio.
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """A database session for tests that need to insert/query data directly."""
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """
    A FastAPI test client with the real app and a test database.

    How dependency injection works in tests:
      FastAPI uses `Depends(get_session)` to inject DB sessions into endpoints.
      We override that dependency to inject our test session instead.
      This means every endpoint call in tests uses the in-memory SQLite DB.
    """
    test_settings = Settings(
        database_url=TEST_DATABASE_URL,
        environment="test",
        neo4j_uri="bolt://localhost:7687",
        neo4j_password="test",
        qdrant_url="http://localhost:6333",
        redis_url="redis://localhost:6379/0",
    )

    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def override_get_settings() -> Settings:
        return test_settings

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_settings] = override_get_settings

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
