"""
Document model — represents a single source item ingested by the Sentinel Agent.

A Document is anything PathogenIQ reads from the outside world:
  - A PubMed abstract
  - A CDC health advisory
  - A WHO situation report
  - A news article from ProMED or HealthMap
  - A ClinicalTrials.gov record

Every piece of knowledge in the system must trace back to a Document.
This is the foundation of the evidence chain that prevents hallucinations.
"""

import enum
import uuid

from sqlalchemy import Enum, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class DocumentSource(str, enum.Enum):
    """
    Where the document came from. Using str+Enum means the value is stored
    as a string in PostgreSQL, which is human-readable and survives enum
    reordering (unlike integer enums).
    """
    PUBMED = "pubmed"
    BIORXIV = "biorxiv"
    CDC = "cdc"
    WHO = "who"
    CLINICAL_TRIALS = "clinical_trials"
    NEWS = "news"
    PROMED = "promed"
    MANUAL = "manual"       # human-entered records


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"       # ingested, not yet processed
    PROCESSING = "processing" # an agent is currently reading it
    PROCESSED = "processed"   # fully extracted and stored
    FAILED = "failed"         # processing errored; see error_message
    DUPLICATE = "duplicate"   # same external_id already in DB


class Document(UUIDMixin, TimestampMixin, Base):
    """
    Source document — the ground truth anchor for all agent outputs.

    Schema design decisions:
      - external_id: the original identifier (PubMed PMID, DOI, etc.)
        Combined with source, this is a natural unique key that prevents
        duplicate ingestion.
      - raw_content / processed_content: we store both to allow re-processing
        if our extraction logic improves. Never throw away raw data.
      - metadata_json: flexible JSONB field for source-specific fields
        (e.g., MeSH terms for PubMed, trial phase for ClinicalTrials).
        Use this sparingly — if a field is queried often, promote it to a column.
      - embedding_id: foreign reference to the vector in Qdrant. The actual
        embedding lives there; we just store a pointer.
    """

    __tablename__ = "documents"

    # ── Identification ────────────────────────────────────────────────────────
    source: Mapped[DocumentSource] = mapped_column(
        Enum(DocumentSource, name="document_source_enum"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(512), nullable=False)

    # ── Content ───────────────────────────────────────────────────────────────
    title: Mapped[str | None] = mapped_column(String(2048))
    abstract: Mapped[str | None] = mapped_column(Text)
    raw_content: Mapped[str | None] = mapped_column(Text)
    processed_content: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(2048))
    doi: Mapped[str | None] = mapped_column(String(256))
    authors: Mapped[list | None] = mapped_column(JSONB)      # ["Author A", "Author B"]
    published_date: Mapped[str | None] = mapped_column(String(64))

    # ── Processing ────────────────────────────────────────────────────────────
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status_enum"),
        default=DocumentStatus.PENDING,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    # ── Vector embedding pointer ───────────────────────────────────────────────
    # The embedding lives in Qdrant; this is just the UUID Qdrant assigned it.
    embedding_id: Mapped[str | None] = mapped_column(String(128))

    # ── Relevance scoring ─────────────────────────────────────────────────────
    # Calculated by Sentinel Agent; 0.0 = irrelevant, 1.0 = highly relevant
    relevance_score: Mapped[float | None] = mapped_column(Float)

    # ── Relationships ─────────────────────────────────────────────────────────
    citations: Mapped[list["Citation"]] = relationship(
        "Citation", back_populates="document", cascade="all, delete-orphan"
    )

    # ── Database indexes ──────────────────────────────────────────────────────
    __table_args__ = (
        # Unique constraint: same article can't be ingested twice from the same source
        Index(
            "ix_documents_source_external_id",
            "source",
            "external_id",
            unique=True,
        ),
        # Partial index: fast lookup of documents pending processing
        Index(
            "ix_documents_status_pending",
            "status",
            postgresql_where=(
                "status IN ('pending', 'processing')"
            ),
        ),
    )

    def __repr__(self) -> str:
        return f"<Document {self.source.value}:{self.external_id}>"
