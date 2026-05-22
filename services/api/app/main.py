from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
      - @app.on_event is deprecated in FastAPI 0.93+
      - lifespan uses a context manager: code before `yield` runs on startup,
        code after `yield` runs on shutdown. This is cleaner and testable.

    Everything before `yield` must succeed or the app refuses to start.
    This is intentional — if we can't reach the database, there's nothing
    useful the API can do, so we fail fast and let Docker/k8s restart us.
    """
    # ── Startup ──────────────────────────────────────────────────────────────
    configure_logging()
    logger.info("pathogeniq_starting", environment=settings.environment)

    await init_db()

    logger.info("pathogeniq_ready", host="0.0.0.0", port=8000)
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("pathogeniq_shutting_down")
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
        version="0.1.0",
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
        allow_origins=(
            ["*"] if settings.is_development
            else ["https://pathogeniq.yourdomain.com"]
        ),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    # ── Routes ────────────────────────────────────────────────────────────────
    app.include_router(api_router)

    return app


# Module-level app instance — uvicorn imports this
app = create_app()
