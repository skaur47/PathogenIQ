"""drop removed columns and tables

Revision ID: 007
Revises: 006
Create Date: 2026-06-01

Removes columns and tables that are no longer part of the data model:

Columns dropped:
  pathogens.pandemic_potential_score
  pathogens.case_fatality_rate
  pathogens.annual_cases_estimate
  pathogen_hypotheses.priority_score
  outbreaks.location_id  (FK to locations, dropped before locations table)

Tables dropped:
  alerts          — depends on outbreaks
  evidence_scores — depends on outbreaks
  locations       — no longer referenced
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop dependent tables first (FK constraints point to outbreaks and locations)
    op.drop_table("alerts")
    op.drop_table("evidence_scores")

    # Drop location_id from outbreaks before dropping locations table
    op.drop_constraint("outbreaks_location_id_fkey", "outbreaks", type_="foreignkey")
    op.drop_index("ix_outbreaks_location_id", table_name="outbreaks")
    op.drop_column("outbreaks", "location_id")

    # Now safe to drop locations (nothing references it)
    op.drop_table("locations")

    # Drop columns from pathogens
    op.drop_column("pathogens", "pandemic_potential_score")
    op.drop_column("pathogens", "case_fatality_rate")
    op.drop_column("pathogens", "annual_cases_estimate")

    # Drop column from pathogen_hypotheses
    op.drop_column("pathogen_hypotheses", "priority_score")


def downgrade() -> None:
    op.add_column("pathogen_hypotheses", sa.Column("priority_score", sa.Float(), nullable=True))

    op.add_column("pathogens", sa.Column("annual_cases_estimate", sa.Integer(), nullable=True))
    op.add_column("pathogens", sa.Column("case_fatality_rate", sa.Float(), nullable=True))
    op.add_column("pathogens", sa.Column("pandemic_potential_score", sa.Float(), nullable=True))

    op.create_table(
        "locations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("country_code", sa.String(8), nullable=True),
        sa.Column("admin1_code", sa.String(16), nullable=True),
        sa.Column("location_type", sa.String(32), nullable=False, server_default="country"),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("population", sa.Integer(), nullable=True),
        sa.Column("parent_id", sa.UUID(), sa.ForeignKey("locations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_locations_country_code", "locations", ["country_code"])
    op.create_index("ix_locations_name", "locations", ["name"])

    op.add_column("outbreaks", sa.Column("location_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "outbreaks_location_id_fkey", "outbreaks", "locations", ["location_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_outbreaks_location_id", "outbreaks", ["location_id"])

    op.create_table(
        "evidence_scores",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("outbreak_id", sa.UUID(), sa.ForeignKey("outbreaks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("evidence_level", sa.String(64), nullable=False),
        sa.Column("citation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflicting_evidence", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("verifier_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_scores_outbreak_id", "evidence_scores", ["outbreak_id"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("outbreak_id", sa.UUID(), sa.ForeignKey("outbreaks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("acknowledged_by", sa.String(256), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("generated_by_model", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_outbreak_id", "alerts", ["outbreak_id"])
