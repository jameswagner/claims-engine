"""add_idempotency_key_to_remits

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-05-28 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("remits", sa.Column("idempotency_key", sa.String(255), nullable=True))
    op.create_unique_constraint("uq_remits_idempotency_key", "remits", ["idempotency_key"])
    op.create_index("ix_remits_idempotency_key", "remits", ["idempotency_key"])


def downgrade() -> None:
    op.drop_index("ix_remits_idempotency_key", table_name="remits")
    op.drop_constraint("uq_remits_idempotency_key", "remits", type_="unique")
    op.drop_column("remits", "idempotency_key")
