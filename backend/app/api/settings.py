import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import ModelSettings
from app.db.session import get_db
from app.model_settings.service import get_or_create, list_available_llm_models
from app.providers.base import ModelProvider
from app.providers.factory import get_provider

logger = logging.getLogger("app.settings")

router = APIRouter(prefix="/settings")


class ModelSettingsOut(BaseModel):
    available_llm_models: list[str]
    embeddings_model: str
    default_model: str
    chat_model: str | None = None
    extraction_model: str | None = None
    orchestration_model: str | None = None


class ModelSettingsUpdate(BaseModel):
    default_model: str | None = None
    chat_model: str | None = None
    extraction_model: str | None = None
    orchestration_model: str | None = None


def _out(row: ModelSettings, available: list[str]) -> ModelSettingsOut:
    return ModelSettingsOut(
        available_llm_models=available,
        embeddings_model=settings.embedding_model,
        default_model=row.default_model,
        chat_model=row.chat_model,
        extraction_model=row.extraction_model,
        orchestration_model=row.orchestration_model,
    )


async def _list_available_models(provider: ModelProvider) -> list[str]:
    try:
        return await list_available_llm_models(provider)
    except Exception as exc:
        logger.warning("could not list models from the model runtime: %s", exc)
        raise HTTPException(
            status_code=503, detail="Could not reach the model runtime to list available models"
        ) from None


@router.get("/models", response_model=ModelSettingsOut)
async def get_model_settings(
    db: AsyncSession = Depends(get_db), provider: ModelProvider = Depends(get_provider)
) -> ModelSettingsOut:
    row = await get_or_create(db)
    available = await _list_available_models(provider)
    return _out(row, available)


@router.patch("/models", response_model=ModelSettingsOut)
async def update_model_settings(
    request: ModelSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    provider: ModelProvider = Depends(get_provider),
) -> ModelSettingsOut:
    provided = request.model_dump(exclude_unset=True)
    if not provided:
        raise HTTPException(status_code=400, detail="No fields provided")
    if "default_model" in provided and provided["default_model"] is None:
        raise HTTPException(status_code=400, detail="default_model cannot be unset")

    available = await _list_available_models(provider)
    for field, value in provided.items():
        if value is not None and value not in available:
            raise HTTPException(status_code=400, detail=f"Unknown model {value!r} for {field}")

    row = await get_or_create(db)
    for field, value in provided.items():
        setattr(row, field, value)
    await db.commit()

    logger.info("model settings updated: %s", provided)
    return _out(row, available)
