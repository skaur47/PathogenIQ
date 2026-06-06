"""
API response schemas for Document resources.

WHY SEPARATE FROM THE ORM MODEL?
  The SQLAlchemy Document model is the database representation. It has
  internal fields (raw_content, metadata_json) that we don't want to
  expose over the API, and it uses types (UUID, datetime) that need
  serialisation. DocumentRead is the "public face" of a document.

  The `model_config = {"from_attributes": True}` setting enables Pydantic
  to read from ORM object attributes (doc.title) instead of dict keys
  (doc["title"]). This is how FastAPI converts ORM objects → JSON responses
  when you annotate an endpoint with `response_model=DocumentRead`.

WHAT FIELDS ARE OMITTED FROM DocumentRead?
  - raw_content: large field, not useful for list views; available on detail view
  - metadata_json: internal JSONB, internal to the ingestion pipeline
  - error_message: internal, for monitoring dashboards only
  Expose these in a separate DocumentDetailRead schema if needed in Phase 5.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models.document import DocumentSource, DocumentStatus


class DocumentRead(BaseModel):
    """
    Public API representation of a Document.
    Returned by GET /api/v1/documents and GET /api/v1/documents/{id}.
    """

    id: UUID
    source: DocumentSource
    external_id: str
    title: str | None
    abstract: str | None
    url: str | None
    doi: str | None
    authors: list[str] | None
    published_date: str | None
    status: DocumentStatus
    relevance_score: float | None
    embedding_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    """
    Paginated list of documents.

    Why include total, limit, offset?
      The frontend needs these to render pagination controls:
        - total: "showing 50 of 12,847 documents"
        - limit + offset: calculate current page, total pages

    Alternative (cursor pagination):
      For very large datasets (millions of rows), offset pagination slows down
      because PostgreSQL must skip N rows. Cursor pagination (using the last
      seen ID as the next page start) is O(log N). We use offset for now —
      typical document counts in early Phase 2 are in the thousands.
    """

    items: list[DocumentRead]
    total: int
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class DocumentStatusUpdate(BaseModel):
    """Request body for PATCH /api/v1/documents/{id}/status."""

    status: DocumentStatus
