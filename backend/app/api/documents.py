import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document
from app.db.session import get_db
from app.extraction.pipeline import extract_document
from app.ingestion.pipeline import ingest_path
from app.providers.base import ModelProvider
from app.providers.factory import get_provider

logger = logging.getLogger("app.documents")

router = APIRouter(prefix="/documents")


class IngestRequest(BaseModel):
    path: str


class IngestResult(BaseModel):
    path: str
    status: str
    chunks: int
    project_id: str | None = None
    project_resolution: str | None = None
    error: str | None = None


@router.post("/ingest", response_model=list[IngestResult])
async def ingest(
    request: IngestRequest,
    db: AsyncSession = Depends(get_db),
    provider: ModelProvider = Depends(get_provider),
) -> list[IngestResult]:
    root = Path(request.path)
    if not root.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {request.path}")

    results = await ingest_path(db, provider, root)
    if not results:
        raise HTTPException(status_code=400, detail="No .md or .pdf files found at the given path")

    ingest_results = [IngestResult(**result) for result in results]
    for ingest_result in ingest_results:
        if ingest_result.status in ("unchanged", "failed"):
            continue
        document = (await db.execute(select(Document).where(Document.path == ingest_result.path))).scalar_one()
        try:
            outcome = await extract_document(db, provider, document)
        except Exception as exc:
            await db.rollback()
            logger.exception("extraction failed for document %s", ingest_result.path)
            ingest_result.error = str(exc)
            continue
        ingest_result.project_id = str(outcome.project_id) if outcome.project_id else None
        ingest_result.project_resolution = outcome.project_resolution

    return ingest_results
