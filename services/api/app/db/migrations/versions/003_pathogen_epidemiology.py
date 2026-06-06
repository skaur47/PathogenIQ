"""pathogen_epidemiology_fields

Revision ID: 003
Revises: 002
Create Date: 2026-05-27

Adds case_fatality_rate and annual_cases_estimate to pathogens table.
Both are Scholar-synthesized fields and are nullable — existing rows are
unaffected until Scholar re-runs and populates them.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pathogens", sa.Column("case_fatality_rate", sa.Float, nullable=True))
    op.add_column("pathogens", sa.Column("annual_cases_estimate", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("pathogens", "annual_cases_estimate")
    op.drop_column("pathogens", "case_fatality_rate")
