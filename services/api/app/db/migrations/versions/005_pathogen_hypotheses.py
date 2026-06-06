"""pathogen_hypotheses

Revision ID: 005
Revises: 004
Create Date: 2026-05-27

Adds pathogen_hypotheses table — stores Hypothesis Agent outputs:
  - identified research gap
  - proposed therapeutic/vaccine strategy
  - specific wet-lab experiment proposals
  - feasible clinical approaches
  - rationale and priority score
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pathogen_hypotheses",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pathogen_id", sa.UUID(as_uuid=True), sa.ForeignKey("pathogens.id", ondelete="CASCADE"), nullable=False, unique=True),
        # Identified gap in current research landscape
        sa.Column("research_gap", sa.Text, nullable=True),
        # Proposed high-level strategy (therapy, vaccine, repurposed compound, etc.)
        sa.Column("proposed_strategy", sa.Text, nullable=True),
        # Specific wet-lab experiments — numbered, model-specific
        sa.Column("wetlab_experiments", sa.Text, nullable=True),
        # Feasible clinical approaches to control outbreak
        sa.Column("clinical_approaches", sa.Text, nullable=True),
        # Why this strategy is biologically/epidemiologically sound
        sa.Column("rationale", sa.Text, nullable=True),
        # Synthesized strategic recommendation
        sa.Column("overall_recommendation", sa.Text, nullable=True),
        # 0.0–1.0 urgency/opportunity score (computed from profile data)
        sa.Column("priority_score", sa.Float, nullable=True),
        sa.Column("last_synthesized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pathogen_hypotheses_pathogen_id", "pathogen_hypotheses", ["pathogen_id"])


def downgrade() -> None:
    op.drop_index("ix_pathogen_hypotheses_pathogen_id", table_name="pathogen_hypotheses")
    op.drop_table("pathogen_hypotheses")
