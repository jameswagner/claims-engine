"""add_submitting_states

Adds SUBMITTING and CLEARINGHOUSE_REJECTED to ClaimStatus.

ClaimStatus is stored as VARCHAR (native_enum=False) so no ALTER TYPE is needed —
the column already accepts any string value. This migration is a no-op at the
database level but serves as a documented checkpoint in the migration history.

Revision ID: f4b5c6d7e8f9
Revises: e5f6a7b8c9d0
Create Date: 2026-05-30 12:00:00.000000

"""
from typing import Sequence, Union

revision: str = "f4b5c6d7e8f9"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # VARCHAR column — no schema change required. New values are enforced
    # at the Python/ORM layer, not the database layer.
    pass


def downgrade() -> None:
    pass
