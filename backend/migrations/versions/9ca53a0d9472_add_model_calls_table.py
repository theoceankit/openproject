"""add model_calls table

Revision ID: 9ca53a0d9472
Revises: 25481133a24d
Create Date: 2026-07-10 00:18:18.860372

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9ca53a0d9472'
down_revision: Union[str, Sequence[str], None] = '25481133a24d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('model_calls',
    sa.Column('operation', sa.String(), nullable=False),
    sa.Column('call_site', sa.String(), nullable=True),
    sa.Column('model', sa.String(), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=True),
    sa.Column('completion_tokens', sa.Integer(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('model_calls')
