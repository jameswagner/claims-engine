"""add_place_of_service_to_claims

Revision ID: a1b2c3d4e5f6
Revises: f4b5c6d7e8f9
Create Date: 2026-06-13

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'f4b5c6d7e8f9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('claims', sa.Column('place_of_service', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('claims', 'place_of_service')
