"""pathogen_mentions table

Revision ID: 002
Revises: 001
Create Date: 2026-05-26 00:00:00.000000

Adds pathogen_mentions table for Sentinel Agent output.
Each row records that a specific pathogen was mentioned in a specific
document, along with a count and source text spans for traceability.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pathogen_mentions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.func.gen_random_uuid(),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pathogen_name", sa.String(512), nullable=False),
        sa.Column("mention_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("source_spans", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_pathogen_mentions_document_id", "pathogen_mentions", ["document_id"]
    )
    op.create_index(
        "ix_pathogen_mentions_pathogen_name", "pathogen_mentions", ["pathogen_name"]
    )
    op.create_index(
        "ix_pathogen_mentions_doc_pathogen",
        "pathogen_mentions",
        ["document_id", "pathogen_name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("pathogen_mentions")
