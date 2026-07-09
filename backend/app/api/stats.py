from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Conversation, Document, ModelCall, Project
from app.db.session import get_db

router = APIRouter(prefix="/stats")


class CorpusStats(BaseModel):
    projects: int
    documents: int
    chunks: int
    conversations: int


class UsageStats(BaseModel):
    model_calls: int
    tokens: int


class StatsOut(BaseModel):
    corpus: CorpusStats
    usage: UsageStats


@router.get("", response_model=StatsOut)
async def get_stats(db: AsyncSession = Depends(get_db)) -> StatsOut:
    projects = (await db.execute(select(func.count()).select_from(Project))).scalar_one()
    documents = (
        await db.execute(select(func.count()).select_from(Document).where(Document.origin != "attachment"))
    ).scalar_one()
    chunks = (
        await db.execute(
            select(func.count())
            .select_from(Chunk)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.origin != "attachment")
        )
    ).scalar_one()
    conversations = (await db.execute(select(func.count()).select_from(Conversation))).scalar_one()

    model_calls = (await db.execute(select(func.count()).select_from(ModelCall))).scalar_one()
    tokens = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(func.coalesce(ModelCall.prompt_tokens, 0) + func.coalesce(ModelCall.completion_tokens, 0)),
                    0,
                )
            ).select_from(ModelCall)
        )
    ).scalar_one()

    return StatsOut(
        corpus=CorpusStats(projects=projects, documents=documents, chunks=chunks, conversations=conversations),
        usage=UsageStats(model_calls=model_calls, tokens=tokens),
    )
