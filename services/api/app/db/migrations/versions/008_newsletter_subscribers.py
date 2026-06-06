"""Add newsletter_subscribers table.

Revision ID: 008
Revises: 007
Create Date: 2026-06-05
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "newsletter_subscribers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("unsubscribe_token", UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("subscribed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_newsletter_subscribers_email", "newsletter_subscribers", ["email"], unique=True)
    op.create_index("ix_newsletter_subscribers_token", "newsletter_subscribers", ["unsubscribe_token"], unique=True)
    op.create_index("ix_newsletter_subscribers_active", "newsletter_subscribers", ["is_active"])


def downgrade() -> None:
    op.drop_table("newsletter_subscribers")
