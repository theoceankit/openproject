from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.providers.base import ModelProvider
from app.providers.factory import get_provider

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/db")
async def health_db(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/health/model")
async def health_model(provider: ModelProvider = Depends(get_provider)) -> dict[str, object]:
    generated = await provider.generate(
        "Reply with the single word: ok", system="Follow instructions exactly.", call_site="health"
    )
    embeddings = await provider.embed(["health check"], call_site="health")
    return {"generated": generated, "embedding_dim": len(embeddings[0])}
