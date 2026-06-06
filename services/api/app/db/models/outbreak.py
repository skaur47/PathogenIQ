"""
Outbreak model — the central entity of the surveillance system.

An Outbreak is a detected occurrence of a pathogen at a location,
during a time window, with an associated risk assessment.

This is what the Sentinel Agent creates when it detects a pattern
across multiple Documents pointing to a new or escalating event.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class OutbreakStatus(str, enum.Enum):
    SUSPECTED = "suspected"      # signal detected but not confirmed
    CONFIRMED = "confirmed"      # WHO/CDC official confirmation
    MONITORING = "monitoring"    # confirmed, being watched
    ESCALATING = "escalating"    # case count rising significantly
    CONTAINED = "contained"      # spread appears controlled
    RESOLVED = "resolved"        # no new cases for 2 incubation periods


class RiskLevel(str, enum.Enum):
    """
    Five-level risk taxonomy aligned with WHO and CDC frameworks.
    Mapped to colors in the frontend: green/yellow/orange/red/purple.
    """
    LOW = "low"               # localized, well-controlled
    MODERATE = "moderate"     # regional spread, standard containment
    HIGH = "high"             # multi-country spread or high CFR
    CRITICAL = "critical"     # pandemic potential or mass casualty threat
    UNKNOWN = "unknown"       # insufficient data to assess


class Outbreak(UUIDMixin, TimestampMixin, Base):
    """
    A detected disease outbreak event.

    Key design choices:
      - pathogen_id + location_id: foreign keys enforce referential integrity.
        You can't have an outbreak for a pathogen that doesn't exist in our DB.
      - case_count / death_count: nullable — early in an outbreak these numbers
        are often unknown. Never fabricate 0 when data is absent.
      - risk_score (0.0–1.0): a continuous score from the Sentinel Agent's
        epidemic risk model. risk_level is the discretized human-readable version.
      - agent_reasoning: stores the LLM's explanation for its risk assessment.
        This is the "show your work" field — critical for the human review step.
      - source_document_ids: JSONB array of Document UUIDs that triggered this
        outbreak detection. Full audit trail.
    """

    __tablename__ = "outbreaks"

    # ── Identity ──────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(1024), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # ── Foreign keys ──────────────────────────────────────────────────────────
    pathogen_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pathogens.id", ondelete="RESTRICT"),
        nullable=False,
    )

    pathogen: Mapped["Pathogen"] = relationship("Pathogen", back_populates="outbreaks", lazy="raise")

    # ── Timeline ──────────────────────────────────────────────────────────────
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Epidemiology ──────────────────────────────────────────────────────────
    case_count: Mapped[int | None] = mapped_column(Integer)
    death_count: Mapped[int | None] = mapped_column(Integer)
    hospitalized_count: Mapped[int | None] = mapped_column(Integer)
    # Case Fatality Rate = deaths / confirmed_cases. NOT infection fatality rate.
    case_fatality_rate: Mapped[float | None] = mapped_column(Float)

    # ── Risk assessment ───────────────────────────────────────────────────────
    status: Mapped[OutbreakStatus] = mapped_column(
        Enum(OutbreakStatus, name="outbreak_status_enum"),
        default=OutbreakStatus.SUSPECTED,
        nullable=False,
    )
    risk_level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, name="risk_level_enum"),
        default=RiskLevel.UNKNOWN,
        nullable=False,
    )
    risk_score: Mapped[float | None] = mapped_column(Float)  # 0.0–1.0

    # ── AI audit trail ────────────────────────────────────────────────────────
    # The LLM's step-by-step reasoning. Required for human review.
    agent_reasoning: Mapped[str | None] = mapped_column(Text)
    # Document UUIDs that triggered this detection
    source_document_ids: Mapped[list | None] = mapped_column(JSONB)
    # Model that generated this record
    detected_by_model: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (
        Index("ix_outbreaks_pathogen_id", "pathogen_id"),
        Index("ix_outbreaks_status", "status"),
        Index("ix_outbreaks_risk_level", "risk_level"),
        Index("ix_outbreaks_detected_at", "detected_at"),
    )

    def __repr__(self) -> str:
        return f"<Outbreak {self.name} [{self.status.value}]>"
