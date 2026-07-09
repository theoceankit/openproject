"""add conversation title

Revision ID: a33f212985d0
Revises: 97e3959654de
Create Date: 2026-07-09 17:08:23.075000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a33f212985d0'
down_revision: Union[str, Sequence[str], None] = '97e3959654de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('conversations', sa.Column('title', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conversations', 'title')
