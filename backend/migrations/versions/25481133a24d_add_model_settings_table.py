"""add model_settings table

Revision ID: 25481133a24d
Revises: a33f212985d0
Create Date: 2026-07-09 19:43:14.983499

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '25481133a24d'
down_revision: Union[str, Sequence[str], None] = 'a33f212985d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('model_settings',
    sa.Column('default_model', sa.String(), nullable=False),
    sa.Column('chat_model', sa.String(), nullable=True),
    sa.Column('extraction_model', sa.String(), nullable=True),
    sa.Column('orchestration_model', sa.String(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('model_settings')
