"""
ARQ WorkerSettings — the entry point for the background worker process.

HOW TO RUN THE WORKER:
  docker compose up worker          # via Docker (recommended)
  arq app.workers.settings.WorkerSettings   # directly (for debugging)

HOW ARQ SCHEDULING WORKS:
  ARQ uses Redis as both the task queue and the cron trigger store.
  When the worker starts, it reads WorkerSettings and:
    1. Registers `functions` so they can be called via enqueue_job().
    2. Schedules `cron_jobs` — at each scheduled time, ARQ enqueues the
       function automatically (as if the API had called enqueue_job).
    3. Runs `on_startup` / `on_shutdown` hooks once per worker process.

CRON SCHEDULE DESIGN:
  ProMED/CIDRAP: every 6 hours (00:02, 06:02, 12:02, 18:02 UTC)
    WHY: CIDRAP publishes a small number of curated articles daily; 6-hour
    polling captures all posts within a business-day cycle.

  CDC + WHO (PAHO+ECDC) + News: every 4 hours
    WHY: RSS feeds refresh on alert publication. 4-hour polling gives timely
    coverage without hammering servers. Minute offsets stagger DB writes:
      CDC   → :05
      WHO   → :10  (runs PAHO + ECDC sequentially)
      News  → :15  (5 feeds fetched concurrently)

NOTE ON PUBMED:
  PubMed is excluded from Phase 2 cron. It is collected in Phase 3 by the
  Scholar (LiteratureAgent) which pairs it with embedding generation and
  structured NCBI ESearch queries. See collectors/pubmed.py for the collector.

REDIS SETTINGS:
  _get_redis_settings() is called at class-definition time (module import).
  At that point, the .env file is already loaded (pydantic-settings reads it
  on Settings() construction). So reading settings here is safe.

RESULT RETENTION:
  keep_result_s = 7 days. ARQ stores the return value of each task in Redis
  so we can query it via GET /ingestion/jobs/{job_id}. After 7 days the key
  expires automatically. Bump this if you want longer audit history.

JOB TIMEOUT:
  job_timeout = 600 seconds (10 minutes). Collectors now fetch full article
  text for up to 150 documents after the relevance+date filter. With 10
  concurrent requests at 8s timeout each, worst-case is ~120s for article
  fetching on top of the RSS parse — 600s gives comfortable headroom.
"""

import structlog
from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings
from app.core.logging import configure_logging

from .tasks import (
    task_collect_cdc,
    task_collect_news,
    task_collect_promed,
    task_collect_who,
    task_run_dedup,
    task_run_full_pipeline,
    task_run_hypothesis,
    task_run_research,
    task_run_scholar,
    task_run_sentinel,
    task_run_verifier_hypothesis,
    task_run_verifier_research,
    task_send_newsletter,
    task_sync_graph,
)

logger = structlog.get_logger(__name__)


async def on_startup(ctx: dict) -> None:
    """
    Runs once when the worker process starts.
    Good place to initialise shared resources (DB engine, HTTP session pool).
    We just configure logging — DB sessions are created per-task via AsyncSessionLocal.
    """
    configure_logging()
    settings = get_settings()
    logger.info(
        "worker_startup",
        environment=settings.environment,
        functions=[
            "task_collect_cdc",
            "task_collect_who",
            "task_collect_promed",
            "task_collect_news",
            "task_run_sentinel",
            "task_run_scholar",
            "task_run_dedup",
            "task_sync_graph",
        ],
    )


async def on_shutdown(ctx: dict) -> None:
    """
    Runs once when the worker process stops (SIGTERM or SIGINT).
    Dispose the SQLAlchemy engine to cleanly close all DB connections.
    Without this, PostgreSQL may log "unexpected EOF on client connection".
    """
    from app.db.session import engine
    await engine.dispose()
    logger.info("worker_shutdown")


def _get_redis_settings() -> RedisSettings:
    """Parse the REDIS_URL from settings into an ARQ RedisSettings object."""
    settings = get_settings()
    return RedisSettings.from_dsn(settings.redis_url)


class WorkerSettings:
    """
    ARQ reads this class to configure the worker process.
    All attributes are class-level (not instance) — ARQ inspects them directly.
    """

    # ── Task registry ────────────────────────────────────────────────────────
    # Every function that can be enqueued (via API or cron) must be listed here.
    functions = [
        task_collect_cdc,
        task_collect_who,
        task_collect_promed,
        task_collect_news,
        task_run_sentinel,            # extract pathogen mentions from ingested docs
        task_run_scholar,             # synthesize biological profiles from PubMed
        task_run_dedup,               # merge duplicate pathogen records
        task_sync_graph,              # sync pathogen graph to Neo4j
        task_run_research,            # deep literature synthesis + source links
        task_run_hypothesis,          # research gap identification + strategy synthesis
        task_run_verifier_research,   # quality-gate after Research Agent
        task_run_verifier_hypothesis, # quality-gate after Hypothesis Agent
        task_run_full_pipeline,       # complete end-to-end run (scheduled daily at 02:00 UTC)
        task_send_newsletter,         # daily digest email to subscribers (08:00 UTC)
    ]

    # ── Cron schedule ─────────────────────────────────────────────────────────
    # cron(func, hour={...}, minute=N) means: run at those hours:minute, UTC.
    cron_jobs = [
        # Intra-day collection — feed new documents into the DB throughout the day
        cron(task_collect_promed, hour={0, 6, 12, 18}, minute=2),
        cron(task_collect_cdc,    hour={0, 4, 8, 12, 16, 20}, minute=5),
        cron(task_collect_who,    hour={0, 4, 8, 12, 16, 20}, minute=10),
        cron(task_collect_news,   hour={0, 4, 8, 12, 16, 20}, minute=15),
        # Full pipeline — runs every night at 02:00 UTC (quiet hours)
        # Processes everything collected during the day: Sentinel → Scholar →
        # Dedup → Research → Hypothesis → Graph Sync.
        cron(task_run_full_pipeline, hour=2, minute=0),
        # Daily digest — sent every morning at 08:00 UTC, after the pipeline completes.
        cron(task_send_newsletter, hour=8, minute=0),
    ]

    # ── Lifecycle hooks ───────────────────────────────────────────────────────
    on_startup = on_startup
    on_shutdown = on_shutdown

    # ── Redis connection ──────────────────────────────────────────────────────
    redis_settings = _get_redis_settings()

    # ── Job settings ──────────────────────────────────────────────────────────
    # Keep task results in Redis for 7 days (job status + return value).
    keep_result_s: int = 60 * 60 * 24 * 7

    # Kill a task if it runs longer than this many seconds.
    # Full-pipeline task runs all agents sequentially — allow up to 8 hours
    # for slow Ollama CPU inference over many pathogens.
    job_timeout: int = 28800

    # Max concurrent tasks. PubMed batching is CPU+IO bound; 10 is safe.
    max_jobs: int = 10
