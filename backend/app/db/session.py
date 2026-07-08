import logging
import time
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.logging import request_id_var

engine = create_async_engine(settings.database_url)
async_session = async_sessionmaker(engine, expire_on_commit=False)

sql_logger = logging.getLogger("app.db.queries")


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _record_query_start(conn, cursor, statement, parameters, context, executemany) -> None:
    if settings.log_sql_queries:
        context._query_start_time = time.monotonic()


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _log_query(conn, cursor, statement, parameters, context, executemany) -> None:
    if not settings.log_sql_queries:
        return
    start = getattr(context, "_query_start_time", None)
    duration_ms = (time.monotonic() - start) * 1000 if start is not None else 0.0
    sql_logger.info(
        "%s [%.1f ms] request_id=%s", " ".join(statement.split()), duration_ms, request_id_var.get() or "-"
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
