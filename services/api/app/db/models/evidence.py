"""
Citation model — links agent-generated claims back to source Documents.
"""

import uuid

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Citation(UUIDMixin, TimestampMixin, Base):
    """
    Links a specific claim (text) to the Document that supports it.

    This is the anti-hallucination mechanism: every AI-generated claim
    must be grounded in a real Document. If the Verifier Agent cannot
    find a Document that supports a claim, that claim is flagged.

    excerpt: the exact text span from the Document that was used.
    page_or_section: where in the document (for long PDFs or reports).
    relevance_score: how relevant is this citation to the claim (0.0–1.0)?
    """

    __tablename__ = "citations"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)
    page_or_section: Mapped[str | None] = mapped_column(String(256))
    relevance_score: Mapped[float | None] = mapped_column(Float)
    cited_by_agent: Mapped[str | None] = mapped_column(String(128))  # "scholar", "verifier", etc.

    document: Mapped["Document"] = relationship("Document", back_populates="citations")  # noqa: F821

    __table_args__ = (
        Index("ix_citations_document_id", "document_id"),
    )
