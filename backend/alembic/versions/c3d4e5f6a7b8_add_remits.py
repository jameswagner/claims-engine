"""add_remits

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-05-28 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "remits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("total_billed", sa.Numeric(10, 2), nullable=False),
        sa.Column("total_allowed", sa.Numeric(10, 2), nullable=False),
        sa.Column("total_paid", sa.Numeric(10, 2), nullable=False),
    )
    op.create_index("ix_remits_claim_id", "remits", ["claim_id"], unique=True)

    op.create_table(
        "remit_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("remit_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("remits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("action_required", sa.String(), nullable=False),
    )
    op.create_index("ix_remit_codes_remit_id", "remit_codes", ["remit_id"])


def downgrade() -> None:
    op.drop_index("ix_remit_codes_remit_id", table_name="remit_codes")
    op.drop_table("remit_codes")
    op.drop_index("ix_remits_claim_id", table_name="remits")
    op.drop_table("remits")
