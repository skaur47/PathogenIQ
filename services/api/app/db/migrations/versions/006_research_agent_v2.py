"""research_agent_v2 — specialized sub-agent summary columns

Revision ID: 006
Revises: 005
Create Date: 2026-05-28

Adds four dedicated summary columns to pathogen_research_summaries, one per
specialized sub-agent introduced in Phase 4 v2:

  molecular_biology_summary   — genome, structure, host-pathogen interaction
  experiments_summary         — in vitro / in vivo assays and experimental findings
  therapeutics_summary        — vaccines, antivirals, antibodies, clinical trials
  clinical_epi_summary        — outbreak dynamics, risk factors, public health measures

The original four columns (infection_mechanism_summary, wet_lab_summary,
clinical_trial_summary, vaccine_therapy_summary) are kept for backward
compatibility with Phase 4 v1 data.

No ALTER TYPE is needed for the article_category enum because it uses
native_enum=False (VARCHAR storage) — adding new ArticleCategory values to the
Python enum is sufficient.
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pathogen_research_summaries",
        sa.Column("molecular_biology_summary", sa.Text, nullable=True),
    )
    op.add_column(
        "pathogen_research_summaries",
        sa.Column("experiments_summary", sa.Text, nullable=True),
    )
    op.add_column(
        "pathogen_research_summaries",
        sa.Column("therapeutics_summary", sa.Text, nullable=True),
    )
    op.add_column(
        "pathogen_research_summaries",
        sa.Column("clinical_epi_summary", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pathogen_research_summaries", "clinical_epi_summary")
    op.drop_column("pathogen_research_summaries", "therapeutics_summary")
    op.drop_column("pathogen_research_summaries", "experiments_summary")
    op.drop_column("pathogen_research_summaries", "molecular_biology_summary")
