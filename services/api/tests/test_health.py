"""
Health endpoint tests.

These tests verify:
  1. The liveness endpoint always returns 200
  2. The readiness endpoint returns 200 when DB is connected
  3. The full health endpoint returns the expected response shape
  4. The full health endpoint degrades gracefully when a service is unreachable

Why test health endpoints?
  Health checks are infrastructure glue — they're read by load balancers
  and Kubernetes probes. If they break silently, your pods get killed
  or traffic stops routing. A broken health endpoint is worse than no health
  endpoint because it causes mysterious production incidents.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_liveness_returns_200(client: AsyncClient) -> None:
    """
    Liveness probe must always return 200.
    It has no dependencies — if it fails, the process itself is broken.
    """
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"


@pytest.mark.asyncio
async def test_readiness_with_healthy_db(client: AsyncClient) -> None:
    """
    Readiness returns 200 when the database is reachable.
    In tests, the DB is always the in-memory SQLite, so this should always pass.
    """
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"


@pytest.mark.asyncio
async def test_full_health_response_shape(client: AsyncClient) -> None:
    """
    Full health response has the correct schema.
    Services may be 'unreachable' in test environment (no real Qdrant/Redis).
    We only verify the shape, not that all services are healthy.
    """
    response = await client.get("/api/v1/health")
    # The response might be 200 (healthy/degraded) but the shape must be correct
    assert response.status_code == 200
    data = response.json()

    assert "status" in data
    assert data["status"] in ("healthy", "degraded", "unhealthy")
    assert "version" in data
    assert data["version"] == "0.1.0"
    assert "environment" in data
    assert "services" in data
    assert "postgres" in data["services"]
    assert "qdrant" in data["services"]
    assert "redis" in data["services"]


@pytest.mark.asyncio
async def test_full_health_postgres_healthy(client: AsyncClient) -> None:
    """
    PostgreSQL (via test SQLite) must always show as healthy in unit tests.
    If it doesn't, the test setup itself is broken.
    """
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["services"]["postgres"]["status"] == "healthy"
    assert data["services"]["postgres"]["latency_ms"] is not None
    assert data["services"]["postgres"]["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_full_health_service_status_fields(client: AsyncClient) -> None:
    """Each service entry must have status, and optionally latency_ms and error."""
    response = await client.get("/api/v1/health")
    data = response.json()

    for service_name, service_data in data["services"].items():
        assert "status" in service_data, f"{service_name} missing 'status' field"
        assert service_data["status"] in (
            "healthy", "degraded", "unreachable"
        ), f"{service_name} has unexpected status: {service_data['status']}"


@pytest.mark.asyncio
async def test_openapi_docs_available(client: AsyncClient) -> None:
    """
    OpenAPI docs should be accessible in non-production environments.
    This also verifies the FastAPI app registered routes correctly.
    """
    response = await client.get("/docs")
    assert response.status_code == 200
