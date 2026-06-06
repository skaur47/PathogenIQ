"""
Research models — store per-pathogen literature findings from the Research Agent.

Two tables:
  research_articles      — one row per PubMed article per pathogen, with an
                           LLM-generated summary of that article's key findings.
  pathogen_research_summaries — one row per pathogen; holds category-level and
                           overall landscape summaries synthesised from all articles.

Article categories:
  infection_mechanism — how the pathogen enters and replicates in host cells
  wet_lab             — in vitro / in vivo experimental findings
  clinical_trial      — human trials (phase I–III, observational)
  vaccine_therapy     — vaccines, antivirals, and other countermeasures
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class ArticleCategory(str, enum.Enum):
    # Phase 4 v1 — original categories (kept for backward compat with existing data)
    INFECTION_MECHANISM = "infection_mechanism"
    WET_LAB = "wet_lab"
    CLINICAL_TRIAL = "clinical_trial"
    VACCINE_THERAPY = "vaccine_therapy"
    # Phase 4 v2 — specialized sub-agents (non-overlapping domains)
    MOLECULAR_BIOLOGY = "molecular_biology"
    EXPERIMENTS = "experiments"
    THERAPEUTICS = "therapeutics"
    CLINICAL_EPIDEMIOLOGY = "clinical_epidemiology"


class ResearchArticle(UUIDMixin, TimestampMixin, Base):
    """
    A single PubMed article associated with a pathogen, with an LLM summary.

    pmid is nullable because in future we may index non-PubMed sources (bioRxiv,
    ClinicalTrials.gov) that don't have a PMID.  The unique constraint on
    (pathogen_id, pmid) prevents duplicate indexing for PubMed articles; rows
    with pmid=NULL are not considered equal by PostgreSQL's unique index, so
    multiple non-PubMed records per pathogen are allowed.
    """
    __tablename__ = "research_articles"

    pathogen_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pathogens.id", ondelete="CASCADE"),
        nullable=False,
    )
    pmid: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[str | None] = mapped_column(Text)
    published_date: Mapped[str | None] = mapped_column(String(20))
    article_category: Mapped[ArticleCategory] = mapped_column(
        Enum(ArticleCategory, name="article_category_enum", native_enum=False),
        nullable=False,
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    article_summary: Mapped[str | None] = mapped_column(Text)

    pathogen: Mapped["Pathogen"] = relationship("Pathogen")  # noqa: F821

    __table_args__ = (
        Index("ix_research_articles_pathogen_id", "pathogen_id"),
        Index("ix_research_articles_category", "article_category"),
    )

    def __repr__(self) -> str:
        return f"<ResearchArticle pmid={self.pmid} category={self.article_category}>"


class PathogenResearchSummary(UUIDMixin, TimestampMixin, Base):
    """
    Aggregated research landscape for a pathogen, produced by the Research Agent.

    One row per pathogen (enforced by UNIQUE on pathogen_id).
    Each category_summary field synthesises all articles in that category.
    overall_summary covers the full research landscape in one narrative.
    """
    __tablename__ = "pathogen_research_summaries"

    pathogen_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pathogens.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # Phase 4 v1 legacy columns — populated by original Research Agent runs
    infection_mechanism_summary: Mapped[str | None] = mapped_column(Text)
    wet_lab_summary: Mapped[str | None] = mapped_column(Text)
    clinical_trial_summary: Mapped[str | None] = mapped_column(Text)
    vaccine_therapy_summary: Mapped[str | None] = mapped_column(Text)
    # Phase 4 v2 specialized sub-agent columns — populated by new multi-agent runs
    molecular_biology_summary: Mapped[str | None] = mapped_column(Text)
    experiments_summary: Mapped[str | None] = mapped_column(Text)
    therapeutics_summary: Mapped[str | None] = mapped_column(Text)
    clinical_epi_summary: Mapped[str | None] = mapped_column(Text)
    overall_summary: Mapped[str | None] = mapped_column(Text)
    article_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_researched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pathogen: Mapped["Pathogen"] = relationship("Pathogen")  # noqa: F821

    __table_args__ = (
        Index("ix_pathogen_research_summaries_pathogen_id", "pathogen_id"),
    )

    def __repr__(self) -> str:
        return f"<PathogenResearchSummary pathogen_id={self.pathogen_id}>"
