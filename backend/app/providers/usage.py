import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ModelCall
from app.db.session import async_session

logger = logging.getLogger("app.usage")


async def record_model_call(
    session: AsyncSession,
    *,
    operation: str,
    call_site: str | None,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> None:
    session.add(
        ModelCall(
            operation=operation,
            call_site=call_site,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
    )
    await session.commit()


async def record_model_call_best_effort(
    *,
    operation: str,
    call_site: str | None,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> None:
    """Record a call in its own session, never raising.

    Usage stats are best-effort telemetry for the Statistics settings panel; a DB hiccup here
    must not turn into a failed chat answer or a failed extraction.
    """
    try:
        async with async_session() as session:
            await record_model_call(
                session,
                operation=operation,
                call_site=call_site,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
    except Exception:
        logger.warning("failed to record model call usage", exc_info=True)
