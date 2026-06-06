"""
PathogenHypothesis — stores Hypothesis Agent outputs for one pathogen.

One record per pathogen (unique pathogen_id). Re-running the agent upserts
the record rather than appending, so the table always reflects the latest
synthesis pass.

Sections:
  research_gap         — what is critically under-researched right now
  proposed_strategy    — the specific therapeutic/vaccine/intervention approach
  wetlab_experiments   — numbered, model-specific experiments to run next
  clinical_approaches  — feasible clinical/epidemiological steps
  rationale            — why this strategy given the evidence
  overall_recommendation — synthesized strategic summary
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class PathogenHypothesis(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "pathogen_hypotheses"

    pathogen_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pathogens.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    research_gap: Mapped[str | None] = mapped_column(Text)
    proposed_strategy: Mapped[str | None] = mapped_column(Text)
    wetlab_experiments: Mapped[str | None] = mapped_column(Text)
    clinical_approaches: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    overall_recommendation: Mapped[str | None] = mapped_column(Text)

    last_synthesized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_pathogen_hypotheses_pathogen_id", "pathogen_id"),
    )

    def __repr__(self) -> str:
        return f"<PathogenHypothesis pathogen_id={self.pathogen_id}>"
