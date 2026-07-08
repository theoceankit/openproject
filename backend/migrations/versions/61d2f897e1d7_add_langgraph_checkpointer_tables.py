"""add langgraph checkpointer tables

Revision ID: 61d2f897e1d7
Revises: f3da9f1b48fe
Create Date: 2026-06-24 01:39:25.534090

"""
import asyncio
import threading
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '61d2f897e1d7'
down_revision: Union[str, Sequence[str], None] = 'f3da9f1b48fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _run_setup_in_thread() -> None:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from app.core.config import settings

    async def _run_setup() -> None:
        async with AsyncPostgresSaver.from_conn_string(_psycopg_url(settings.database_url)) as saver:
            await saver.setup()

    asyncio.run(_run_setup())


def upgrade() -> None:
    """Upgrade schema."""
    # setup() runs CREATE INDEX CONCURRENTLY, which Postgres refuses inside a transaction
    # block and which otherwise deadlocks waiting on Alembic's own ambient transaction on
    # this migration's connection. autocommit_block() commits that transaction first; the
    # actual call still runs on a separate thread/event loop, independent of env.py's
    # already-running asyncio loop.
    with op.get_context().autocommit_block():
        thread = threading.Thread(target=_run_setup_in_thread)
        thread.start()
        thread.join()


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE IF EXISTS checkpoint_writes, checkpoint_blobs, checkpoints, checkpoint_migrations CASCADE")
