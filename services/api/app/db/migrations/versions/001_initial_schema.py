"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-20 00:00:00.000000

This migration creates the complete Phase 1 schema:
  - documents       — source articles, reports, feeds
  - pathogens       — pathogen reference table
  - locations       — geographic hierarchy
  - outbreaks       — detected disease events
  - evidence_scores — confidence scoring for claims
  - citations       — source grounding for all claims
  - alerts          — human-facing notifications
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Create enum types ────────────────────────────────────────────────────
    # PostgreSQL enums must be created before the tables that use them.
    # Use postgresql.ENUM.create() with checkfirst=False, then wrap in
    # a try-except to catch DuplicateObjectError gracefully.

    enums_to_create = [
        postgresql.ENUM(
            "pubmed", "biorxiv", "cdc", "who", "clinical_trials", "news", "promed", "manual",
            name="document_source_enum",
        ),
        postgresql.ENUM(
            "pending", "processing", "processed", "failed", "duplicate",
            name="document_status_enum",
        ),
        postgresql.ENUM(
            "virus", "bacterium", "fungus", "parasite", "prion", "unknown",
            name="pathogen_category_enum",
        ),
        postgresql.ENUM(
            "suspected", "confirmed", "monitoring", "escalating", "contained", "resolved",
            name="outbreak_status_enum",
        ),
        postgresql.ENUM(
            "low", "moderate", "high", "critical", "unknown",
            name="risk_level_enum",
        ),
        postgresql.ENUM(
            "systematic_review", "rct", "cohort_study", "case_control",
            "case_series", "expert_opinion", "ai_inferred",
            name="evidence_level_enum",
        ),
        postgresql.ENUM(
            "info", "warning", "critical",
            name="alert_severity_enum",
        ),
    ]

    for enum in enums_to_create:
        try:
            enum.create(op.get_bind(), checkfirst=False)
        except Exception as e:
            # Ignore DuplicateObjectError; type already exists
            if "already exists" not in str(e):
                raise

    # ── documents ────────────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("source", sa.Enum(name="document_source_enum", create_constraint=False, native_enum=False), nullable=False),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("title", sa.String(2048), nullable=True),
        sa.Column("abstract", sa.Text, nullable=True),
        sa.Column("raw_content", sa.Text, nullable=True),
        sa.Column("processed_content", sa.Text, nullable=True),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column("doi", sa.String(256), nullable=True),
        sa.Column("authors", postgresql.JSONB, nullable=True),
        sa.Column("published_date", sa.String(64), nullable=True),
        sa.Column("status", sa.Enum(name="document_status_enum", create_constraint=False, native_enum=False), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("metadata_json", postgresql.JSONB, nullable=True),
        sa.Column("embedding_id", sa.String(128), nullable=True),
        sa.Column("relevance_score", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_source_external_id", "documents", ["source", "external_id"], unique=True)
    op.create_index("ix_documents_status_pending", "documents", ["status"],
                    postgresql_where=sa.text("status IN ('pending', 'processing')"))

    # ── pathogens ─────────────────────────────────────────────────────────────
    op.create_table(
        "pathogens",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("species_name", sa.String(512), nullable=False),
        sa.Column("common_name", sa.String(512), nullable=True),
        sa.Column("category", sa.Enum(name="pathogen_category_enum", create_constraint=False, native_enum=False), nullable=False, server_default="unknown"),
        sa.Column("ncbi_taxonomy_id", sa.String(64), nullable=True),
        sa.Column("ictv_id", sa.String(128), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("genome_type", sa.String(64), nullable=True),
        sa.Column("transmission_routes", postgresql.JSONB, nullable=True),
        sa.Column("reservoir_hosts", postgresql.JSONB, nullable=True),
        sa.Column("who_priority", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("pandemic_potential_score", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("species_name"),
    )
    op.create_index("ix_pathogens_species_name", "pathogens", ["species_name"])
    op.create_index("ix_pathogens_ncbi_taxonomy_id", "pathogens", ["ncbi_taxonomy_id"])

    # ── locations ─────────────────────────────────────────────────────────────
    op.create_table(
        "locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("country_code", sa.String(8), nullable=True),
        sa.Column("admin1_code", sa.String(16), nullable=True),
        sa.Column("location_type", sa.String(32), nullable=False, server_default="country"),
        sa.Column("latitude", sa.Float, nullable=True),
        sa.Column("longitude", sa.Float, nullable=True),
        sa.Column("population", sa.Integer, nullable=True),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["parent_id"], ["locations.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_locations_country_code", "locations", ["country_code"])
    op.create_index("ix_locations_name", "locations", ["name"])

    # ── outbreaks ─────────────────────────────────────────────────────────────
    op.create_table(
        "outbreaks",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("name", sa.String(1024), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("pathogen_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("case_count", sa.Integer, nullable=True),
        sa.Column("death_count", sa.Integer, nullable=True),
        sa.Column("hospitalized_count", sa.Integer, nullable=True),
        sa.Column("case_fatality_rate", sa.Float, nullable=True),
        sa.Column("status", sa.Enum(name="outbreak_status_enum", create_constraint=False, native_enum=False), nullable=False, server_default="suspected"),
        sa.Column("risk_level", sa.Enum(name="risk_level_enum", create_constraint=False, native_enum=False), nullable=False, server_default="unknown"),
        sa.Column("risk_score", sa.Float, nullable=True),
        sa.Column("agent_reasoning", sa.Text, nullable=True),
        sa.Column("source_document_ids", postgresql.JSONB, nullable=True),
        sa.Column("detected_by_model", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pathogen_id"], ["pathogens.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_outbreaks_pathogen_id", "outbreaks", ["pathogen_id"])
    op.create_index("ix_outbreaks_location_id", "outbreaks", ["location_id"])
    op.create_index("ix_outbreaks_status", "outbreaks", ["status"])
    op.create_index("ix_outbreaks_risk_level", "outbreaks", ["risk_level"])
    op.create_index("ix_outbreaks_detected_at", "outbreaks", ["detected_at"])

    # ── evidence_scores ───────────────────────────────────────────────────────
    op.create_table(
        "evidence_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("outbreak_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_text", sa.Text, nullable=False),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column("evidence_level", sa.Enum(name="evidence_level_enum", create_constraint=False, native_enum=False), nullable=False),
        sa.Column("citation_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("conflicting_evidence", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("verifier_notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["outbreak_id"], ["outbreaks.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_evidence_scores_outbreak_id", "evidence_scores", ["outbreak_id"])

    # ── citations ─────────────────────────────────────────────────────────────
    op.create_table(
        "citations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_text", sa.Text, nullable=False),
        sa.Column("excerpt", sa.Text, nullable=True),
        sa.Column("page_or_section", sa.String(256), nullable=True),
        sa.Column("relevance_score", sa.Float, nullable=True),
        sa.Column("cited_by_agent", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_citations_document_id", "citations", ["document_id"])

    # ── alerts ────────────────────────────────────────────────────────────────
    op.create_table(
        "alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("outbreak_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("severity", sa.Enum(name="alert_severity_enum", create_constraint=False, native_enum=False), nullable=False),
        sa.Column("acknowledged", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("acknowledged_by", sa.String(256), nullable=True),
        sa.Column("review_notes", sa.Text, nullable=True),
        sa.Column("generated_by_model", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["outbreak_id"], ["outbreaks.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_alerts_outbreak_id", "alerts", ["outbreak_id"])
    op.create_index(
        "ix_alerts_unacknowledged_critical", "alerts", ["severity", "acknowledged"],
        postgresql_where=sa.text("acknowledged = false"),
    )


def downgrade() -> None:
    """Drop all tables and enum types in reverse dependency order."""
    op.drop_table("alerts")
    op.drop_table("citations")
    op.drop_table("evidence_scores")
    op.drop_table("outbreaks")
    op.drop_table("locations")
    op.drop_table("pathogens")
    op.drop_table("documents")

    # Drop enum types after tables that use them are gone
    for enum_name in [
        "alert_severity_enum",
        "evidence_level_enum",
        "risk_level_enum",
        "outbreak_status_enum",
        "pathogen_category_enum",
        "document_status_enum",
        "document_source_enum",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
