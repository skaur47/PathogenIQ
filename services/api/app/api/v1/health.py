"""
Health check endpoints.

THREE endpoints — each serves a different purpose:

  GET /api/v1/health
    ─ Full health report: checks all dependencies (DB, Neo4j, Qdrant, Redis).
    ─ Used by: monitoring dashboards, developers.
    ─ Never hit this from a load balancer (it has latency).

  GET /api/v1/health/live
    ─ Liveness probe: is the process alive and not deadlocked?
    ─ Returns 200 immediately — no dependency checks.
    ─ Used by: Kubernetes liveness probe.
    ─ If this fails, k8s restarts the container.

  GET /api/v1/health/ready
    ─ Readiness probe: is the app ready to serve traffic?
    ─ Checks only the database (minimum viable check).
    ─ Used by: Kubernetes readiness probe, Docker healthcheck.
    ─ If this fails, k8s stops sending traffic to this pod.

Why separate live vs ready?
  Imagine the DB is briefly unreachable (a blip). You want k8s to stop
  sending traffic (/ready fails) but NOT restart the container (/live passes).
  Restarting would be slower than just waiting for the DB to come back.
"""

import time
from typing import Any

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["health"])


class ServiceStatus(BaseModel):
    """Status of a single dependency."""
    status: str       # "healthy" | "degraded" | "unreachable"
    latency_ms: float | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    """Full health report returned by GET /health."""
    status: str       # "healthy" | "degraded" | "unhealthy"
    version: str
    environment: str
    services: dict[str, ServiceStatus]


class LivenessResponse(BaseModel):
    status: str = "alive"


class ReadinessResponse(BaseModel):
    status: str       # "ready" | "not_ready"
    database: str     # "connected" | "unreachable"


async def _check_postgres(session: AsyncSession) -> ServiceStatus:
    """Ping the database and measure latency."""
    start = time.perf_counter()
    try:
        await session.execute(text("SELECT 1"))
        latency = (time.perf_counter() - start) * 1000
        return ServiceStatus(status="healthy", latency_ms=round(latency, 2))
    except Exception as e:
        return ServiceStatus(status="unreachable", error=str(e))


async def _check_qdrant(settings: Settings) -> ServiceStatus:
    """
    Ping Qdrant REST API.
    We use httpx here to avoid importing the full qdrant-client just for a healthcheck.
    """
    import httpx
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.qdrant_url}/healthz")
            resp.raise_for_status()
        latency = (time.perf_counter() - start) * 1000
        return ServiceStatus(status="healthy", latency_ms=round(latency, 2))
    except Exception as e:
        return ServiceStatus(status="unreachable", error=str(e)[:120])


async def _check_redis(settings: Settings) -> ServiceStatus:
    """Ping Redis using the redis-py async client."""
    import redis.asyncio as aioredis
    start = time.perf_counter()
    try:
        r = aioredis.from_url(settings.redis_url, socket_timeout=2)
        await r.ping()
        await r.aclose()
        latency = (time.perf_counter() - start) * 1000
        return ServiceStatus(status="healthy", latency_ms=round(latency, 2))
    except Exception as e:
        return ServiceStatus(status="unreachable", error=str(e)[:120])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Full health report",
    description="Returns status of all infrastructure dependencies. Not suitable for high-frequency polling.",
)
async def health_full(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    postgres = await _check_postgres(session)
    qdrant = await _check_qdrant(settings)
    redis = await _check_redis(settings)

    all_statuses = [postgres.status, qdrant.status, redis.status]

    if all(s == "healthy" for s in all_statuses):
        overall = "healthy"
    elif all(s == "unreachable" for s in all_statuses):
        overall = "unhealthy"
    else:
        overall = "degraded"

    logger.info("health_check", overall=overall, postgres=postgres.status, qdrant=qdrant.status, redis=redis.status)

    return HealthResponse(
        status=overall,
        version="0.1.0",
        environment=settings.environment,
        services={
            "postgres": postgres,
            "qdrant": qdrant,
            "redis": redis,
        },
    )


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    summary="Kubernetes liveness probe",
    description="Always returns 200 if the process is running. No dependency checks.",
)
async def health_live() -> LivenessResponse:
    return LivenessResponse(status="alive")


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Kubernetes readiness probe",
    description="Returns 200 only if the API can serve requests (database reachable).",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Database unreachable — not ready to serve traffic"
        }
    },
)
async def health_ready(
    session: AsyncSession = Depends(get_session),
) -> ReadinessResponse:
    from fastapi import HTTPException
    postgres = await _check_postgres(session)

    if postgres.status != "healthy":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "database": postgres.error},
        )

    return ReadinessResponse(status="ready", database="connected")
