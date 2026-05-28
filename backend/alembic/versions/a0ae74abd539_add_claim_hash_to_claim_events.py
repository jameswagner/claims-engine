"""add_claim_hash_to_claim_events

Revision ID: a0ae74abd539
Revises: cb2110d9253d
Create Date: 2026-05-26 16:18:09.856861

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a0ae74abd539'
down_revision: Union[str, None] = 'cb2110d9253d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("claim_events", sa.Column("claim_hash", sa.String(32), nullable=True))
    op.create_index("ix_claim_events_claim_hash", "claim_events", ["claim_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_claim_events_claim_hash", table_name="claim_events")
    op.drop_column("claim_events", "claim_hash")
