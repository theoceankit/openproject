import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db

logger = logging.getLogger("app.admin")

router = APIRouter(prefix="/admin")


class ResetResult(BaseModel):
    status: str


def _clear_storage_dir() -> None:
    """Remove every durable stored file copy. Safe to call unconditionally: reset just
    truncated every Document row, so every file under storage_dir is now orphaned."""
    storage_dir = Path(settings.storage_dir)
    if storage_dir.exists():
        shutil.rmtree(storage_dir)


@router.post("/reset", response_model=ResetResult)
async def reset(db: AsyncSession = Depends(get_db)) -> ResetResult:
    # alembic_version must survive a data reset, truncating it would corrupt Alembic's
    # migration-version bookkeeping.
    result = await db.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = current_schema() AND tablename != 'alembic_version'"
        )
    )
    table_names = [row[0] for row in result.all()]
    if not table_names:
        _clear_storage_dir()
        return ResetResult(status="ok")

    quoted = ", ".join(f'"{name}"' for name in table_names)
    try:
        # NOWAIT: fail immediately instead of blocking on a concurrent transaction's lock
        # and then silently truncating data it just wrote once it commits.
        await db.execute(text(f"LOCK TABLE {quoted} IN ACCESS EXCLUSIVE MODE NOWAIT"))
        await db.execute(text(f"TRUNCATE TABLE {quoted} CASCADE"))
        await db.commit()
    except DBAPIError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Database is busy (an ingest or chat request may be in progress); retry shortly.",
        ) from None

    _clear_storage_dir()

    logger.info("reset %d tables", len(table_names))
    return ResetResult(status="ok")
