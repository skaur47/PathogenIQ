from fastapi import APIRouter
from app.config import get_settings
from app.api.v1 import health

settings = get_settings()

api_router = APIRouter(prefix=settings.api_v1_prefix)

# ── v1 routes ─────────────────────────────────────────────────────────────────
# Each module is included separately so it's easy to add/remove feature groups.
# Phase 2 will add: outbreaks, documents, pathogens routers.
# Phase 3 will add: search, agents routers.

api_router.include_router(health.router)
