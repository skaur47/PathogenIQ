from collections.abc import AsyncGenerator

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# ── Engine ────────────────────────────────────────────────────────────────────
# The engine manages the connection pool. It is created once at module load
# and reused for the lifetime of the process.
#
# pool_size: how many connections to keep open permanently.
#   - Too small: requests queue waiting for a connection.
#   - Too large: you hit PostgreSQL's max_connections limit (default 100).
#   - Rule of thumb: (number_of_workers × 2) + headroom.
#
# max_overflow: extra connections allowed above pool_size under heavy load.
#   These are opened on demand and closed when no longer needed.
#
# pool_pre_ping: before handing out a connection, send "SELECT 1" to check
#   it's still alive. Without this, you get cryptic errors after network blips
#   or PostgreSQL restarts.
#
# pool_recycle: close and reopen connections older than N seconds. Prevents
#   issues with firewalls that silently drop idle long-lived connections.
engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=settings.db_echo,
)

# ── Session factory ───────────────────────────────────────────────────────────
# async_sessionmaker is a factory that produces AsyncSession objects.
# expire_on_commit=False: after commit(), SQLAlchemy normally expires all
# attributes so they reload from the DB on next access. With async, that
# reload would be a second await. expire_on_commit=False avoids this — the
# object stays usable after commit without a second round-trip.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def init_db() -> None:
    """
    Verify database connectivity on startup.

    Why retry? Docker Compose starts services concurrently. The API container
    often starts before PostgreSQL is fully ready to accept connections. Without
    retry, the API crashes immediately. With tenacity, it retries with
    exponential backoff (2s, 4s, 8s, 10s, 10s) before giving up.

    The healthcheck in docker-compose also helps, but the `depends_on: condition:
    service_healthy` check only confirms PostgreSQL accepted a TCP connection —
    not that it can execute queries. This double-check is safer.
    """
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info(
        "database_connected",
        host=settings.database_url.split("@")[-1] if "@" in settings.database_url else "unknown",
    )


async def close_db() -> None:
    """Dispose the connection pool on shutdown."""
    await engine.dispose()
    logger.info("database_disconnected")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session per request.

    Usage in an endpoint:
        @router.get("/outbreaks")
        async def list_outbreaks(session: AsyncSession = Depends(get_session)):
            ...

    Why a generator (yield) instead of returning the session directly?
      - The `finally` block runs after the endpoint returns, ensuring the
        session is always closed even if the endpoint raises an exception.
      - If an exception occurs mid-request, we rollback to undo partial writes.
        Without rollback, partial data could be committed if something else
        triggers a flush.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
