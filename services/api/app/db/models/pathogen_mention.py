"""
PathogenMention — one record per (document, pathogen) pair.

Created by the Sentinel Agent after processing each ingested document.
The aggregate view (pathogen → total_mentions across all docs) is computed
by a SQL GROUP BY query rather than stored redundantly.

Why per-document records instead of a single global counter?
  A global counter loses provenance. Per-document records let you ask:
  "Which articles mention H5N1?" and "How confident are we in this count?"
  The source_spans field shows exactly which sentences triggered each
  extraction, enabling human review of the Sentinel's outputs.
"""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class PathogenMention(UUIDMixin, TimestampMixin, Base):
    """
    Records that a specific pathogen was mentioned in a specific document.

    pathogen_name: canonical, normalized name resolved by the Sentinel Agent.
      Examples: "SARS-CoV-2", "Influenza A H5N1", "Mpox virus", "Vibrio cholerae O1"
      Normalization maps aliases ("COVID", "coronavirus", "COVID-19" → "SARS-CoV-2")
      so the frequency table counts are not inflated by synonym variation.

    mention_count: how many times the pathogen (or its aliases) appeared
      in the document's raw_content + title combined.

    source_spans: 1–3 short text excerpts showing where the pathogen appeared.
      Stored for traceability — lets a human verify Sentinel extractions without
      re-reading the full article.
    """

    __tablename__ = "pathogen_mentions"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    pathogen_name: Mapped[str] = mapped_column(String(512), nullable=False)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_spans: Mapped[list | None] = mapped_column(JSONB)

    document: Mapped["Document"] = relationship("Document")  # noqa: F821

    __table_args__ = (
        Index("ix_pathogen_mentions_document_id", "document_id"),
        Index("ix_pathogen_mentions_pathogen_name", "pathogen_name"),
        Index(
            "ix_pathogen_mentions_doc_pathogen",
            "document_id",
            "pathogen_name",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<PathogenMention {self.pathogen_name!r} in doc {self.document_id}>"
