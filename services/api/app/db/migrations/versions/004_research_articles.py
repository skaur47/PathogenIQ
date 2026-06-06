"""Add research_articles and pathogen_research_summaries tables.

Revision ID: 004
Revises: 003
Create Date: 2026-05-27
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_articles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pathogen_id", UUID(as_uuid=True), sa.ForeignKey("pathogens.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pmid", sa.String(32), nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("authors", sa.Text, nullable=True),
        sa.Column("published_date", sa.String(20), nullable=True),
        sa.Column("article_category", sa.String(30), nullable=False),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("abstract", sa.Text, nullable=True),
        sa.Column("article_summary", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint("pathogen_id", "pmid", name="uq_research_articles_pathogen_pmid"),
    )
    op.create_index("ix_research_articles_pathogen_id", "research_articles", ["pathogen_id"])
    op.create_index("ix_research_articles_category", "research_articles", ["article_category"])

    op.create_table(
        "pathogen_research_summaries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pathogen_id", UUID(as_uuid=True), sa.ForeignKey("pathogens.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("infection_mechanism_summary", sa.Text, nullable=True),
        sa.Column("wet_lab_summary", sa.Text, nullable=True),
        sa.Column("clinical_trial_summary", sa.Text, nullable=True),
        sa.Column("vaccine_therapy_summary", sa.Text, nullable=True),
        sa.Column("overall_summary", sa.Text, nullable=True),
        sa.Column("article_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_researched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pathogen_research_summaries_pathogen_id", "pathogen_research_summaries", ["pathogen_id"])


def downgrade() -> None:
    op.drop_table("pathogen_research_summaries")
    op.drop_table("research_articles")
