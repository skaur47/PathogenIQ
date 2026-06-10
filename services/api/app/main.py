from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.logging import configure_logging
from app.db.session import close_db, init_db
from app.api.router import api_router

logger = structlog.get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Application lifespan manager.

    Why lifespan instead of @app.on_event("startup")?
      - @app.on_event is deprecated in FastAPI 0.93+.
      - lifespan uses a context manager: code before `yield` runs on startup,
        code after `yield` runs on shutdown. This is cleaner and testable.

    Everything before `yield` must succeed or the app refuses to start —
    except the ARQ pool, which is optional. If Redis is down, the API still
    serves documents and health checks; only the ingestion trigger endpoints
    will return 503 until Redis comes back.
    """
    # ── Startup ───────────────────────────────────────────────────────────────
    configure_logging()
    logger.info("pathogeniq_starting", environment=settings.environment)

    await init_db()

    # Initialise ARQ Redis pool (Phase 2).
    # Stored on app.state so ingestion endpoints can enqueue jobs.
    # We do NOT fail startup if Redis is unavailable — the API remains useful
    # for read-only operations (documents, health). Ingestion endpoints will
    # return 503 and the health endpoint will report Redis as "unreachable".
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        app.state.arq_redis = await create_pool(
            RedisSettings.from_dsn(settings.redis_url)
        )
        logger.info("arq_pool_connected", redis_url=settings.redis_url)
    except Exception as exc:
        logger.warning("arq_pool_unavailable", error=str(exc))
        app.state.arq_redis = None

    logger.info("pathogeniq_ready", host="0.0.0.0", port=8000)
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("pathogeniq_shutting_down")

    if getattr(app.state, "arq_redis", None) is not None:
        await app.state.arq_redis.aclose()
        logger.info("arq_pool_closed")

    await close_db()
    logger.info("pathogeniq_stopped")


def create_app() -> FastAPI:
    """
    Application factory.

    Why a factory function instead of a module-level `app = FastAPI()`?
      - Tests can call create_app() with overridden settings to get isolated instances.
      - Makes it clear which settings control which behaviors.
    """
    app = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        description=(
            "Real-time infectious disease intelligence and therapeutic discovery platform. "
            "All AI-generated outputs require expert review before clinical application."
        ),
        lifespan=lifespan,
        # Hide docs in production — OpenAPI exposes your full API surface
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Cross-Origin Resource Sharing: allows the Next.js frontend (port 3000)
    # to call the API (port 8000). In production this should list only your
    # actual domain (e.g., "https://pathogeniq.yourdomain.com").
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.is_development else [o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    # ── Routes ────────────────────────────────────────────────────────────────
    app.include_router(api_router)

    # ── CORS-safe error handler ───────────────────────────────────────────────
    # Unhandled exceptions bypass the CORS middleware and return responses with
    # no Access-Control-Allow-Origin header, causing the browser to show a CORS
    # error instead of the real 500. This handler ensures the header is present.
    allowed = ["*"] if settings.is_development else [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        origin = request.headers.get("origin", "")
        headers = {}
        if "*" in allowed or origin in allowed:
            headers["Access-Control-Allow-Origin"] = origin or "*"
        logger.error("unhandled_exception", path=request.url.path, error=str(exc))
        return JSONResponse(status_code=500, content={"detail": "Internal server error"}, headers=headers)

    return app


# Module-level app instance — uvicorn imports this
app = create_app()
