"""
Intermediate data schemas for the collector → ingestion pipeline.

WHY a separate schema layer?
  The collector fetches raw data from the internet. The Document SQLAlchemy model
  is the DB representation. These two shouldn't be the same type because:

    1. Collectors run before we have a DB session — they shouldn't import ORM models.
    2. The DB model has fields a collector can't know (id, created_at, embedding_id).
    3. Different collectors provide different subsets of fields. CollectedDocument
       uses optional fields so a CDC RSS entry (no DOI, no authors) can live next
       to a PubMed abstract that has all of them.

  CollectedDocument is the "data envelope" passed from a collector to
  IngestionService, which maps it onto the Document ORM model.
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.db.models.document import DocumentSource


class CollectedDocument(BaseModel):
    """
    Raw document as returned by a collector, before it touches the database.

    Fields:
      source:         Which platform this came from (DocumentSource enum value).
      external_id:    The platform's own identifier (PMID for PubMed, URL for RSS).
                      Combined with source, this forms the deduplication key.
      title:          Article / alert headline.
      abstract:       Summary text (PubMed abstract, RSS description, etc.).
      raw_content:    Full text if available; abstract otherwise. Stored in DB for
                      re-processing if extraction logic improves.
      url:            Link back to the original record.
      doi:            Digital Object Identifier (PubMed only in Phase 2).
      authors:        List of author names in "LastName First" format.
      published_date: Publication date as a string (formats vary by source).
      metadata:       Source-specific extras (MeSH terms, feed tags, etc.) stored
                      as JSONB. Useful in Phase 3 for NLP enrichment.
    """

    source: DocumentSource
    external_id: str
    title: str | None = None
    abstract: str | None = None
    raw_content: str | None = None
    url: str | None = None
    doi: str | None = None
    authors: list[str] = Field(default_factory=list)
    published_date: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionResult(BaseModel):
    """
    Summary returned by IngestionService after a collector run.

    Used by:
      - ARQ task functions (returned as a dict, stored in Redis)
      - GET /api/v1/ingestion/jobs/{job_id} endpoint (shown to the caller)
      - Logging and monitoring dashboards
    """

    source: str
    query: str | None = None
    new_documents: int = 0
    duplicates: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    collected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
