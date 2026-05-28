"""replace_claim_hash_with_idempotency_key

Revision ID: f3a1b2c4e5d6
Revises: a0ae74abd539
Create Date: 2026-05-27 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a1b2c4e5d6'
down_revision: Union[str, None] = 'a0ae74abd539'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_claim_events_claim_hash", table_name="claim_events")
    op.drop_column("claim_events", "claim_hash")
    op.add_column("claim_events", sa.Column("idempotency_key", sa.String(255), nullable=True))
    op.create_index("ix_claim_events_idempotency_key", "claim_events", ["idempotency_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_claim_events_idempotency_key", table_name="claim_events")
    op.drop_column("claim_events", "idempotency_key")
    op.add_column("claim_events", sa.Column("claim_hash", sa.String(32), nullable=True))
    op.create_index("ix_claim_events_claim_hash", "claim_events", ["claim_hash"], unique=True)
