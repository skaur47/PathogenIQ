"""
Location model — represents a geographic entity in the surveillance system.

Locations form a hierarchy: Country → Region/Province → City.
This hierarchy lets us aggregate outbreak data at any level
(e.g., "all outbreaks in Southeast Asia").
"""

from sqlalchemy import Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Location(UUIDMixin, TimestampMixin, Base):
    """
    Geographic entity.

    Why store lat/lng?
      - Enables proximity queries: "find all outbreaks within 500km of Bangkok"
      - Powers the map visualization in the Next.js frontend
      - Lets us compute geographic spread rate of an outbreak

    Why ISO codes?
      - country_code (ISO 3166-1 alpha-2): "US", "TH", "ZA"
      - admin1_code (ISO 3166-2): "US-NY", "TH-10" (Bangkok)
      These are standard, unambiguous identifiers. "United States" vs "USA" vs
      "US" is a naming problem; "US" (ISO 3166-1 alpha-2) is not.

    parent_id enables the hierarchy:
      Thailand (country) → Bangkok (city)
      The "Bangkok" record has parent_id pointing to "Thailand".
    """

    __tablename__ = "locations"

    # ── Identity ──────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(8))    # ISO 3166-1 alpha-2
    admin1_code: Mapped[str | None] = mapped_column(String(16))    # ISO 3166-2 (province/state)
    location_type: Mapped[str] = mapped_column(
        String(32), default="country", nullable=False
    )  # "country" | "region" | "city" | "district"

    # ── Geography ─────────────────────────────────────────────────────────────
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    population: Mapped[int | None] = mapped_column()

    # ── Hierarchy ─────────────────────────────────────────────────────────────
    parent_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="SET NULL")
    )
    parent: Mapped["Location | None"] = relationship(
        "Location", remote_side="Location.id", back_populates="children"
    )
    children: Mapped[list["Location"]] = relationship(
        "Location", back_populates="parent"
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    outbreaks: Mapped[list["Outbreak"]] = relationship(  # noqa: F821
        "Outbreak", back_populates="location"
    )

    __table_args__ = (
        Index("ix_locations_country_code", "country_code"),
        Index("ix_locations_name", "name"),
    )

    def __repr__(self) -> str:
        return f"<Location {self.name} ({self.country_code})>"
