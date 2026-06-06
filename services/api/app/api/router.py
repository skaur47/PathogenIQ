from fastapi import APIRouter

from app.config import get_settings
from app.api.v1 import agents, documents, health, ingestion, newsletter

settings = get_settings()

api_router = APIRouter(prefix=settings.api_v1_prefix)

# ── v1 routes ─────────────────────────────────────────────────────────────────
# Each module is included separately so it's easy to add/remove feature groups.
# Phase 3 will add: search, agents routers.
# Phase 4 will add: knowledge-graph routers.

api_router.include_router(health.router)
api_router.include_router(documents.router)   # Phase 2: document ingestion CRUD
api_router.include_router(ingestion.router)   # Phase 2: trigger + job status
api_router.include_router(agents.router)      # Phase 3: AI agent triggers + outputs
api_router.include_router(newsletter.router)  # Newsletter: subscribe / unsubscribe
