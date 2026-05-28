"""add_financial_fields_to_claims

Revision ID: b1c2d3e4f5a6
Revises: f3a1b2c4e5d6
Create Date: 2026-05-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'f3a1b2c4e5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("claims", sa.Column("billed_amount", sa.Numeric(10, 2), nullable=False, server_default="0"))
    op.add_column("claims", sa.Column("allowed_amount", sa.Numeric(10, 2), nullable=True))
    op.add_column("claims", sa.Column("paid_amount", sa.Numeric(10, 2), nullable=True))
    op.add_column("claims", sa.Column("patient_responsibility", sa.Numeric(10, 2), nullable=True))
    op.add_column("claims", sa.Column("adjustment_reason", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("claims", "adjustment_reason")
    op.drop_column("claims", "patient_responsibility")
    op.drop_column("claims", "paid_amount")
    op.drop_column("claims", "allowed_amount")
    op.drop_column("claims", "billed_amount")
