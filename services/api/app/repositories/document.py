import uuid
from typing import Sequence

from sqlalchemy import select, update

from app.db.models.document import Document, DocumentSource, DocumentStatus
from app.db.session import AsyncSession
from app.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Document)

    async def get_by_external_id(
        self, source: DocumentSource, external_id: str
    ) -> Document | None:
        """
        Look up a document by (source, external_id) — the natural unique key.
        Used by the Sentinel Agent before ingesting: if the document is already
        in the DB, skip it to avoid duplicate processing.
        """
        result = await self._session.execute(
            select(Document).where(
                Document.source == source,
                Document.external_id == external_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_pending(self, limit: int = 50) -> Sequence[Document]:
        """
        Fetch documents waiting to be processed by agents.
        The Sentinel Agent polls this queue to find new work.
        Ordered by created_at to process in arrival order (FIFO).
        """
        result = await self._session.execute(
            select(Document)
            .where(Document.status == DocumentStatus.PENDING)
            .order_by(Document.created_at.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def mark_processing(self, doc_id: uuid.UUID) -> None:
        """Atomically mark a document as being processed."""
        await self._session.execute(
            update(Document)
            .where(Document.id == doc_id)
            .values(status=DocumentStatus.PROCESSING)
        )
        await self._session.flush()

    async def mark_processed(
        self, doc_id: uuid.UUID, processed_content: str, embedding_id: str | None = None
    ) -> None:
        """Mark a document as fully processed."""
        await self._session.execute(
            update(Document)
            .where(Document.id == doc_id)
            .values(
                status=DocumentStatus.PROCESSED,
                processed_content=processed_content,
                embedding_id=embedding_id,
            )
        )
        await self._session.flush()

    async def mark_failed(self, doc_id: uuid.UUID, error_message: str) -> None:
        """Record a processing failure with the error details."""
        await self._session.execute(
            update(Document)
            .where(Document.id == doc_id)
            .values(status=DocumentStatus.FAILED, error_message=error_message)
        )
        await self._session.flush()

    async def get_by_source(
        self, source: DocumentSource, limit: int = 100, offset: int = 0
    ) -> Sequence[Document]:
        """Retrieve all documents from a specific source (e.g., all PubMed articles)."""
        result = await self._session.execute(
            select(Document)
            .where(Document.source == source)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()
