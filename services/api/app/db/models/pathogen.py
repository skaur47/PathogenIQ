"""
Pathogen model — represents a single infectious agent in the system.

Examples: SARS-CoV-2, Influenza A H5N1, Mpox, Vibrio cholerae O1.

This is a reference entity: it doesn't change often, but many other
records (Outbreaks, Mutations, Citations) point to it.
"""

import enum

from sqlalchemy import Boolean, Enum, Float, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class PathogenCategory(str, enum.Enum):
    VIRUS = "virus"
    BACTERIUM = "bacterium"
    FUNGUS = "fungus"
    PARASITE = "parasite"
    PRION = "prion"
    UNKNOWN = "unknown"


class Pathogen(UUIDMixin, TimestampMixin, Base):
    """
    A known or suspected infectious pathogen.

    Naming conventions follow standard microbiology:
      - species_name: Binomial name, e.g., "SARS-CoV-2" or "Mycobacterium tuberculosis"
      - common_name: Colloquial name, e.g., "COVID-19 virus"
      - ncbi_taxonomy_id: NCBI Taxonomy database ID — the gold standard for
        unambiguous pathogen identification. If you have this, you can link
        to the full taxonomy tree, protein sequences, and genomes.
      - who_priority: whether WHO lists this as a priority pathogen for R&D.

    Why store taxonomy_id?
      In AI-generated text, "coronavirus" could refer to dozens of species.
      NCBI Taxonomy ID 2697049 unambiguously means SARS-CoV-2. This is
      critical for preventing hallucinations and knowledge graph accuracy.
    """

    __tablename__ = "pathogens"

    # ── Identity ──────────────────────────────────────────────────────────────
    species_name: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    common_name: Mapped[str | None] = mapped_column(String(512))
    category: Mapped[PathogenCategory] = mapped_column(
        Enum(PathogenCategory, name="pathogen_category_enum", native_enum=False),
        default=PathogenCategory.UNKNOWN,
        nullable=False,
    )

    # ── External identifiers ──────────────────────────────────────────────────
    ncbi_taxonomy_id: Mapped[str | None] = mapped_column(String(64))
    ictv_id: Mapped[str | None] = mapped_column(String(128))    # International Committee on Taxonomy of Viruses

    # ── Properties ────────────────────────────────────────────────────────────
    description: Mapped[str | None] = mapped_column(Text)
    genome_type: Mapped[str | None] = mapped_column(String(64))  # "ssRNA+", "dsDNA", etc.
    transmission_routes: Mapped[list | None] = mapped_column(JSONB)  # ["airborne", "droplet"]
    reservoir_hosts: Mapped[list | None] = mapped_column(JSONB)     # ["bats", "rodents"]
    who_priority: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    outbreaks: Mapped[list["Outbreak"]] = relationship(  # noqa: F821
        "Outbreak", back_populates="pathogen"
    )

    __table_args__ = (
        Index("ix_pathogens_species_name", "species_name"),
        Index("ix_pathogens_ncbi_taxonomy_id", "ncbi_taxonomy_id"),
    )

    def __repr__(self) -> str:
        return f"<Pathogen {self.species_name}>"
