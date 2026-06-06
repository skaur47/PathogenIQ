"""
Ingestion API — manually trigger data collection and check job status.

DESIGN: ASYNC REQUEST-RESPONSE PATTERN
  Data collection is too slow (30–60 seconds) to run synchronously inside an
  HTTP request. Instead:

    1. POST /ingestion/trigger
       → enqueues an ARQ job in Redis
       → returns HTTP 202 with a job_id immediately (< 1ms)

    2. GET /ingestion/jobs/{job_id}
       → queries ARQ's Redis for the job status
       → returns status + result when complete

  The client can poll step 2 with exponential backoff (e.g., every 5s → 10s →
  30s) or use Server-Sent Events (added in Phase 5).

  WHY HTTP 202?
    HTTP 200 means "request completed successfully."
    HTTP 202 means "request accepted and will be processed."
    202 signals to the client: don't wait for a result body, use the job_id.

ARQ POOL AVAILABILITY:
  The ARQ Redis pool lives in app.state.arq_redis, initialised in main.py's
  lifespan context. If Redis is unavailable at startup, arq_redis is None and
  all trigger/status endpoints return 503. The health endpoint separately
  reports Redis status so you know why.

JOB STATUS STATES:
  queued      — in Redis queue, waiting for a free worker slot
  in_progress — worker is executing the task function right now
  complete    — task finished; `result` has IngestionResult data
  not_found   — job expired (7-day TTL) or job_id is invalid
  failed      — task raised an exception; `error` has the exception message
"""

import asyncio

import structlog
from arq.jobs import Job, JobStatus
from fastapi import APIRouter, HTTPException, Request, status

from app.schemas.ingestion import JobStatusResponse, TriggerRequest, TriggerResponse

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/ingestion", tags=["ingestion"])

# Maps API source names to ARQ task function names.
# The function name string must match the actual function name in tasks.py.
# PubMed is excluded from Phase 2 — it will be wired via the Scholar agent in Phase 3.
_SOURCE_TO_TASK: dict[str, str] = {
    "cdc": "task_collect_cdc",
    "who": "task_collect_who",
    "promed": "task_collect_promed",
    "news": "task_collect_news",
}


def _get_arq_redis(request: Request):
    """
    Extract the ARQ Redis pool from app.state.
    Raises 503 if the pool wasn't initialised (Redis unavailable at startup).
    """
    arq_redis = getattr(request.app.state, "arq_redis", None)
    if arq_redis is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Task queue is unavailable. "
                "Check Redis connectivity via GET /api/v1/health."
            ),
        )
    return arq_redis


@router.post(
    "/trigger",
    response_model=TriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger data collection",
    description=(
        "Enqueue one or all collector jobs. Returns immediately with a job_id. "
        "Poll GET /ingestion/jobs/{job_id} for completion."
    ),
)
async def trigger_collection(
    body: TriggerRequest,
    request: Request,
) -> TriggerResponse:
    """
    Manually trigger data collection from one or all sources.

    In production this runs automatically via the cron scheduler. Use this
    endpoint to:
      - Run an immediate collection outside the normal schedule
      - Test a new PubMed query
      - Backfill after a collector was down

    When source="all", three jobs are enqueued. The response contains
    the job_id of the first job (pubmed). Poll each individually if needed.
    """
    arq_redis = _get_arq_redis(request)

    if body.source == "all":
        jobs = []
        for task_name in _SOURCE_TO_TASK.values():
            job = await arq_redis.enqueue_job(task_name, max_results=body.max_results)
            if job:
                jobs.append(job)

        if not jobs:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to enqueue any collection jobs.",
            )

        logger.info("ingestion_triggered_all", job_ids=[j.job_id for j in jobs])
        return TriggerResponse(
            job_id=jobs[0].job_id,
            source="all",
            message=(
                f"Enqueued {len(jobs)} collection jobs "
                f"(cdc, who, promed, news). Poll each job_id individually."
            ),
        )

    task_name = _SOURCE_TO_TASK.get(body.source)
    if not task_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown source: {body.source!r}",
        )

    job = await arq_redis.enqueue_job(task_name, max_results=body.max_results)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue job (Redis may be at capacity).",
        )

    logger.info("ingestion_triggered", source=body.source, job_id=job.job_id)
    return TriggerResponse(
        job_id=job.job_id,
        source=body.source,
        message=f"Collection job queued for '{body.source}'.",
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get collection job status",
    description=(
        "Check the status of a job enqueued by POST /ingestion/trigger. "
        "Poll this endpoint until status is 'complete' or 'failed'."
    ),
)
async def get_job_status(
    job_id: str,
    request: Request,
) -> JobStatusResponse:
    """
    Poll for completion of a collection job.

    Recommended polling strategy:
      - First check: 5 seconds after triggering
      - If in_progress: check every 10 seconds
      - Stop when status is "complete" or "failed"
      - Abandon after 10 minutes (job_timeout = 5 minutes, plus buffer)
    """
    arq_redis = _get_arq_redis(request)

    job = Job(job_id, arq_redis)
    job_status = await job.status()

    if job_status == JobStatus.not_found:
        return JobStatusResponse(job_id=job_id, status="not_found")

    result: dict | None = None
    error: str | None = None
    enqueue_time = None
    start_time = None
    finish_time = None

    # For completed jobs, fetch the return value stored in Redis.
    # job.result(timeout=0) returns immediately when the job is complete.
    # If the task function itself raised an exception, job.result() re-raises it.
    # We catch everything so a failed result-fetch never crashes the endpoint.
    if job_status == JobStatus.complete:
        try:
            raw_result = await job.result(timeout=0)
            result = raw_result if isinstance(raw_result, dict) else None
        except Exception as exc:
            error = str(exc)

    # job.info() returns the job definition (enqueue_time, function name, etc.)
    try:
        info = await job.info()
        if info:
            enqueue_time = getattr(info, "enqueue_time", None)
            start_time = getattr(info, "start_time", None)
            finish_time = getattr(info, "finish_time", None)
    except asyncio.TimeoutError:
        pass  # info unavailable — not critical
    except Exception as e:
        logger.debug("job_info_fetch_error", job_id=job_id, error=str(e))

    return JobStatusResponse(
        job_id=job_id,
        status=job_status.value,
        result=result,
        error=error,
        enqueue_time=enqueue_time,
        start_time=start_time,
        finish_time=finish_time,
    )
