import logging
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import ModelSettings
from app.providers.base import ModelProvider

logger = logging.getLogger("app.model_settings")

Task = Literal["chat", "extraction", "orchestration"]

# Ollama has no reliable "modality" flag in /api/tags, so embedding-only models are recognized
# by name instead: none of them are valid choices for generate() (chat/extraction/orchestration).
_EMBEDDING_MODEL_MARKERS = ("embed", "bge", "minilm")


def is_embedding_model(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in _EMBEDDING_MODEL_MARKERS)


async def get_or_create(db: AsyncSession) -> ModelSettings:
    """Return the singleton ModelSettings row, seeding it from env config on first access.

    Runs on every request rather than at startup so it also self-heals after POST /admin/reset
    truncates the table (a dev convenience, not something this module needs to special-case).
    """
    row = (await db.execute(select(ModelSettings))).scalars().first()
    if row is None:
        row = ModelSettings(default_model=settings.llm_model)
        db.add(row)
        await db.flush()
    return row


async def resolve_model(db: AsyncSession, task: Task) -> str:
    """The effective model for a task: its override if set, else the default model."""
    row = await get_or_create(db)
    override = getattr(row, f"{task}_model")
    model = override or row.default_model
    logger.info("resolved %s model: %s (%s)", task, model, "override" if override else "default")
    return model


async def list_available_llm_models(provider: ModelProvider) -> list[str]:
    """Models pulled in Ollama that can serve generate(), i.e. not embedding-only models."""
    models = await provider.list_models()
    return [name for name in models if not is_embedding_model(name)]
