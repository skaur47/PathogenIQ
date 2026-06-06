"""
Documents API — read and status-update endpoints for the Document resource.

WHAT DOCUMENTS ARE:
  Every piece of external knowledge in PathogenIQ (PubMed paper, CDC alert,
  WHO report) is a Document. This router lets you browse, filter, and update
  the processing status of documents.

ENDPOINTS:
  GET  /api/v1/documents               List with optional filtering + pagination
  GET  /api/v1/documents/{id}          Get one document by UUID
  PATCH /api/v1/documents/{id}/status  Update processing status

WHY NO POST (create) OR DELETE?
  Documents are created exclusively by the IngestionService (via collector tasks).
  Manual creation would bypass deduplication logic. We'll never hard-delete a
  document — scientific evidence should have a permanent audit trail.
  If a document is irrelevant, set status=FAILED with an error message.

QUERY PARAMETERS:
  ?source=pubmed|cdc|who|...   filter by data source
  ?status=pending|processing|processed|failed|duplicate
  ?limit=50&offset=0           pagination (max limit: 200)
"""

from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import DocumentSource, DocumentStatus
from app.db.session import get_session
from app.repositories.document import DocumentRepository
from app.schemas.document import DocumentListResponse, DocumentRead, DocumentStatusUpdate

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List documents",
    description="Returns a paginated list of ingested documents with optional filtering.",
)
async def list_documents(
    source: DocumentSource | None = Query(
        default=None,
        description="Filter by data source (pubmed, cdc, who, ...).",
    ),
    status_filter: DocumentStatus | None = Query(
        default=None,
        alias="status",
        description="Filter by processing status (pending, processed, failed, ...).",
    ),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: AsyncSession = Depends(get_session),
) -> DocumentListResponse:
    """
    List documents with optional source and status filters.

    Typical use:
      GET /documents?source=pubmed&status=pending
        → show PubMed papers waiting for AI processing

      GET /documents?source=who
        → show all WHO Disease Outbreak News reports
    """
    repo = DocumentRepository(session)

    # Route to the most specific query available.
    # Order matters: source filter overrides status filter when both given.
    if source:
        items = await repo.get_by_source(source, limit=limit, offset=offset)
        total = await repo.count_by_source(source)
    elif status_filter == DocumentStatus.PENDING:
        items = await repo.get_pending(limit=limit)
        total = await repo.count()
    else:
        items = await repo.get_all(limit=limit, offset=offset)
        total = await repo.count()

    return DocumentListResponse(
        items=[DocumentRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentRead,
    summary="Get document",
    description="Retrieve a single document by its UUID.",
    responses={
        404: {"description": "Document not found"},
    },
)
async def get_document(
    document_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> DocumentRead:
    repo = DocumentRepository(session)
    doc = await repo.get_by_id(document_id)

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found.",
        )

    return DocumentRead.model_validate(doc)


@router.patch(
    "/{document_id}/status",
    response_model=DocumentRead,
    summary="Update document status",
    description=(
        "Update the processing status of a document. "
        "Used by AI agents (Phase 3) to mark documents as processed or failed."
    ),
    responses={
        404: {"description": "Document not found"},
    },
)
async def update_document_status(
    document_id: UUID,
    body: DocumentStatusUpdate,
    session: AsyncSession = Depends(get_session),
) -> DocumentRead:
    """
    Agents use this to mark documents as they process them.

    Typical lifecycle:
      PENDING → PROCESSING (agent picks it up)
      PROCESSING → PROCESSED (extraction successful, embedding stored in Qdrant)
      PROCESSING → FAILED (extraction failed; error_message set separately)

    We expose only status here; other fields (embedding_id, processed_content)
    will be set by dedicated agent endpoints added in Phase 3.
    """
    repo = DocumentRepository(session)
    doc = await repo.get_by_id(document_id)

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found.",
        )

    updated = await repo.update(doc, status=body.status)
    await session.commit()

    logger.info(
        "document_status_updated",
        document_id=str(document_id),
        new_status=body.status.value,
    )
    return DocumentRead.model_validate(updated)
