"""
Shared Pydantic schemas used across services.

Why a shared package?
  When you have multiple services (API, background workers, agents),
  they need to agree on data shapes. If the API defines OutbreakSchema
  and the agent defines its own OutbreakSchema, they drift apart over time.
  A shared package is the single source of truth.

  In Phase 2, when we add Celery workers or separate agent services,
  they'll import from this package rather than duplicating schemas.

Pydantic vs SQLAlchemy models:
  SQLAlchemy models (app/db/models/) are for the database layer.
  They know about columns, relationships, and queries.

  Pydantic models (schemas) are for the API layer and inter-service communication.
  They know about HTTP request/response shapes and validation.

  A key principle: never expose SQLAlchemy models directly to the outside world.
  Always convert to a Pydantic schema first. This prevents:
    - Accidental exposure of internal fields
    - Lazy-load errors (accessing .pathogen outside a session)
    - Coupling your API contract to your DB schema
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    """Base schema with standard config for all PathogenIQ schemas."""

    model_config = ConfigDict(
        from_attributes=True,   # enables Schema.model_validate(orm_obj) — converts SQLAlchemy rows
        use_enum_values=True,   # enums serialize as their string values
        populate_by_name=True,  # allows both field name and alias
    )


class TimestampSchema(BaseSchema):
    """Mixin for schemas that include audit timestamps."""
    created_at: datetime
    updated_at: datetime


class PaginatedResponse(BaseSchema):
    """
    Standard pagination wrapper for list endpoints.

    Why standardize pagination?
      Every list endpoint needs the same metadata: total count, page number,
      has_next. Defining it once prevents each endpoint author from inventing
      their own inconsistent pagination response.

    Usage:
        @router.get("/outbreaks", response_model=PaginatedResponse)
        async def list_outbreaks(...) -> PaginatedResponse:
            items = await outbreak_repo.get_all(limit=limit, offset=offset)
            total = await outbreak_repo.count()
            return PaginatedResponse(
                items=[OutbreakSchema.model_validate(o) for o in items],
                total=total,
                page=page,
                page_size=page_size,
            )
    """
    items: list[Any]
    total: int
    page: int = 1
    page_size: int = 20

    @property
    def has_next(self) -> bool:
        return (self.page * self.page_size) < self.total

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def total_pages(self) -> int:
        if self.page_size == 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size


class ErrorResponse(BaseSchema):
    """Standard error response shape for all API errors."""
    error: str
    detail: str | None = None
    request_id: str | None = None


class ConfidenceScore(BaseSchema):
    """
    Structured confidence representation attached to any AI-generated claim.

    score: 0.0–1.0, where:
      0.0–0.3 = low confidence (treat as speculative)
      0.3–0.7 = moderate confidence (some evidence, needs review)
      0.7–1.0 = high confidence (strong evidence, still requires expert validation)

    Why include requires_human_review?
      Any score below 0.7 automatically sets this to True.
      AI outputs should NEVER be acted upon without human validation in a
      clinical or public health context.
    """
    score: float = Field(..., ge=0.0, le=1.0)
    explanation: str
    evidence_sources: list[str] = Field(default_factory=list)
    requires_human_review: bool = True

    @classmethod
    def low(cls, explanation: str) -> "ConfidenceScore":
        return cls(score=0.2, explanation=explanation, requires_human_review=True)

    @classmethod
    def moderate(cls, explanation: str) -> "ConfidenceScore":
        return cls(score=0.55, explanation=explanation, requires_human_review=True)

    @classmethod
    def high(cls, explanation: str, sources: list[str] | None = None) -> "ConfidenceScore":
        return cls(
            score=0.85,
            explanation=explanation,
            evidence_sources=sources or [],
            requires_human_review=False,
        )
