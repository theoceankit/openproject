import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.memory import build_known_facts_block, describe_fact, record_fact
from app.chat.prompts import (
    CHAT_SYSTEM_PROMPT,
    FACT_UPDATE_SYSTEM_PROMPT,
    QUERY_REWRITE_SYSTEM_PROMPT,
    HistoryTurn,
    build_chat_prompt,
    build_fact_update_prompt,
    build_query_rewrite_prompt,
)
from app.core.config import settings
from app.db.models import Conversation, Message
from app.extraction.schemas import FactUpdateResult
from app.providers.base import ModelProvider
from app.retrieval.search import RetrievedChunk, search_chunks

logger = logging.getLogger("app.chat")


@dataclass
class ChatAnswer:
    conversation_id: uuid.UUID
    answer: str
    sources: list[RetrievedChunk]
    pending_fact: dict | None = None


def _truncate_history(messages: list[Message], max_chars: int) -> list[HistoryTurn]:
    """Keep the most recent whole messages that fit within `max_chars`."""
    selected: list[HistoryTurn] = []
    total = 0
    for message in reversed(messages):
        content = message.content
        total += len(content)
        if total > max_chars:
            if not selected:
                content = content[:max_chars]
            else:
                break
        selected.append(HistoryTurn(role=message.role, content=content))
    selected.reverse()
    return selected


async def answer_question(
    db: AsyncSession,
    provider: ModelProvider,
    message: str,
    conversation: Conversation | None = None,
) -> ChatAnswer:
    """Answer a question grounded in retrieved chunks, within an ongoing conversation."""
    if conversation is None:
        conversation = Conversation()
        db.add(conversation)
        await db.flush()
        history_rows: list[Message] = []
    else:
        history_rows = list(
            (
                await db.execute(
                    select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
                )
            ).scalars()
        )

    user_message = Message(conversation_id=conversation.id, role="user", content=message)
    db.add(user_message)
    await db.flush()

    history = _truncate_history(history_rows, settings.chat_history_max_chars)

    async def _resolve_sources() -> tuple[str, list[RetrievedChunk]]:
        if history:
            rewrite_prompt = build_query_rewrite_prompt(history, message)
            rewritten = await provider.generate(
                rewrite_prompt, system=QUERY_REWRITE_SYSTEM_PROMPT, call_site="query_rewrite"
            )
            query = rewritten.strip() or message
        else:
            query = message
        sources = await search_chunks(db, provider, query, settings.chat_retrieval_limit)
        return query, sources

    async def _resolve_fact_update() -> FactUpdateResult:
        fact_prompt = build_fact_update_prompt(history, message)
        fact_raw = await provider.generate(
            fact_prompt,
            system=FACT_UPDATE_SYSTEM_PROMPT,
            format=FactUpdateResult.model_json_schema(),
            call_site="fact_update",
        )
        return FactUpdateResult.model_validate_json(fact_raw)

    (query, sources), fact_update = await asyncio.gather(_resolve_sources(), _resolve_fact_update())

    fact = await record_fact(db, fact_update, source_message_id=user_message.id)
    pending_fact: dict | None = None
    if fact is not None:
        pending_fact = await describe_fact(db, fact)
        logger.info(
            "conversation %s: recorded pending fact subject=%s/%s predicate=%r",
            conversation.id,
            fact.subject_type,
            fact.subject_id,
            fact.predicate,
        )

    known_facts = await build_known_facts_block(db, query)
    prompt = build_chat_prompt(message, sources, history, known_facts)
    answer = await provider.generate(prompt, system=CHAT_SYSTEM_PROMPT, call_site="chat")

    db.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content=answer,
            sources=[
                {"document_path": s.document_path, "section": s.section, "project_name": s.project_name}
                for s in sources
            ],
        )
    )
    await db.commit()

    logger.info("conversation %s: answered with %d source(s)", conversation.id, len(sources))
    return ChatAnswer(conversation_id=conversation.id, answer=answer, sources=sources, pending_fact=pending_fact)
