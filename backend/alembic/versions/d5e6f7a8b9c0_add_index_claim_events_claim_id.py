"""add_index_claim_events_claim_id

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-05-28 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_claim_events_claim_id", "claim_events", ["claim_id"])


def downgrade() -> None:
    op.drop_index("ix_claim_events_claim_id", table_name="claim_events")
