from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import settings


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@asynccontextmanager
async def get_checkpointer():
    async with AsyncPostgresSaver.from_conn_string(_psycopg_url(settings.database_url)) as saver:
        yield saver
