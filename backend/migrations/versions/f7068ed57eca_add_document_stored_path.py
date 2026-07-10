"""add document stored_path

Revision ID: f7068ed57eca
Revises: 9ca53a0d9472
Create Date: 2026-07-10 20:57:16.202909

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f7068ed57eca'
down_revision: Union[str, Sequence[str], None] = '9ca53a0d9472'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('documents', sa.Column('stored_path', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('documents', 'stored_path')
