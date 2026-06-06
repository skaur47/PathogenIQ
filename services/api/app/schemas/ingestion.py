"""
API request/response schemas for the ingestion endpoints.

The trigger endpoint is async by design:
  POST /ingestion/trigger → 202 Accepted + job_id
  GET  /ingestion/jobs/{job_id} → job status + result

This pattern is called "asynchronous request-response". We never block the
HTTP client waiting for a 30-60 second collection job to finish.

Phase 2 sources: cdc, who, promed, news.
PubMed is reserved for Phase 3 (Scholar agent with embedding pipeline).
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TriggerRequest(BaseModel):
    """
    Body for POST /api/v1/ingestion/trigger.

    source:      Which collector to run. "all" runs all four simultaneously.
    max_results: Cap on documents collected per source after filtering (default 150).
                 All sources prefetch more than this value and apply relevance +
                 14-day date filters before truncating to max_results.
    """

    source: Literal["cdc", "who", "promed", "news", "all"]
    max_results: int = Field(
        default=150,
        ge=1,
        le=500,
        description="Maximum documents to collect per source after filtering.",
    )


class TriggerResponse(BaseModel):
    """
    Returned immediately (HTTP 202) after enqueueing a job.

    The job_id can be used to poll for completion via
    GET /api/v1/ingestion/jobs/{job_id}.
    """

    job_id: str
    source: str
    status: str = "queued"
    message: str


class JobStatusResponse(BaseModel):
    """
    Result of checking an ARQ job's status.

    ARQ job lifecycle:
      queued      → job is in the Redis queue, waiting for a worker
      in_progress → a worker is actively running the task
      complete    → task finished; `result` contains IngestionResult data
      not_found   → job ID is invalid or expired (TTL: 7 days)
      failed      → task raised an unhandled exception; `error` has details

    result: the IngestionResult dict (new_documents, duplicates, errors, etc.)
    error:  exception message if status == "failed"
    """

    job_id: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    enqueue_time: datetime | None = None
    start_time: datetime | None = None
    finish_time: datetime | None = None
