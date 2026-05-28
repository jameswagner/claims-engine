"""add_payor_rules

Revision ID: cb2110d9253d
Revises: e4384232efa6
Create Date: 2026-05-26 08:33:17.290563

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cb2110d9253d'
down_revision: Union[str, None] = 'e4384232efa6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payor_rules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("payer", sa.String(), nullable=False),
        sa.Column(
            "rule_type",
            sa.Enum(
                "ALLOWED_CPT", "EXCLUDED_CPT", "REQUIRE_DIAGNOSIS_PREFIX",
                name="ruletype", native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("cpt_code", sa.String(), nullable=True),
        sa.Column("value", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payor_rules_payer", "payor_rules", ["payer"])


def downgrade() -> None:
    op.drop_index("ix_payor_rules_payer", table_name="payor_rules")
    op.drop_table("payor_rules")
