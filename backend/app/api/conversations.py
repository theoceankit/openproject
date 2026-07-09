import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import Page
from app.db.models import Conversation, ConversationAttachment, Document, Message
from app.db.session import get_db

router = APIRouter(prefix="/conversations")

PREVIEW_MAX_CHARS = 200


class ConversationSummary(BaseModel):
    id: str
    title: str | None
    preview: str
    message_count: int
    updated_at: datetime


class ConversationMessageOut(BaseModel):
    role: str
    content: str
    sources: list[dict] | None = None


class ConversationAttachmentOut(BaseModel):
    document_id: str
    path: str


class ConversationDetail(BaseModel):
    id: str
    title: str | None
    messages: list[ConversationMessageOut]
    attachments: list[ConversationAttachmentOut]


@router.get("", response_model=Page[ConversationSummary])
async def list_conversations(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Page[ConversationSummary]:
    activity_subq = (
        select(
            Message.conversation_id.label("conversation_id"),
            func.count(Message.id).label("message_count"),
            func.max(Message.created_at).label("last_activity"),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )

    last_message_subq = (
        select(
            Message.conversation_id.label("conversation_id"),
            Message.content.label("content"),
            func.row_number()
            .over(partition_by=Message.conversation_id, order_by=Message.created_at.desc())
            .label("rn"),
        )
        .subquery()
    )
    last_message = (
        select(last_message_subq.c.conversation_id, last_message_subq.c.content)
        .where(last_message_subq.c.rn == 1)
        .subquery()
    )

    total = (
        await db.execute(select(func.count()).select_from(activity_subq))
    ).scalar_one()

    rows = (
        await db.execute(
            select(
                Conversation,
                activity_subq.c.message_count,
                activity_subq.c.last_activity,
                last_message.c.content,
            )
            .join(activity_subq, activity_subq.c.conversation_id == Conversation.id)
            .join(last_message, last_message.c.conversation_id == Conversation.id)
            .order_by(activity_subq.c.last_activity.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    items = [
        ConversationSummary(
            id=str(conversation.id),
            title=conversation.title,
            preview=content[:PREVIEW_MAX_CHARS],
            message_count=message_count,
            updated_at=last_activity,
        )
        for conversation, message_count, last_activity, content in rows
    ]
    return Page(items=items, total=total)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)) -> ConversationDetail:
    try:
        parsed_id = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation id")

    conversation = await db.get(Conversation, parsed_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = (
        (
            await db.execute(
                select(Message).where(Message.conversation_id == parsed_id).order_by(Message.created_at)
            )
        )
        .scalars()
        .all()
    )

    attachments = (
        await db.execute(
            select(ConversationAttachment, Document)
            .join(Document, Document.id == ConversationAttachment.document_id)
            .where(ConversationAttachment.conversation_id == parsed_id)
        )
    ).all()

    return ConversationDetail(
        id=str(conversation.id),
        title=conversation.title,
        messages=[
            ConversationMessageOut(role=m.role, content=m.content, sources=m.sources) for m in messages
        ],
        attachments=[
            ConversationAttachmentOut(document_id=str(document.id), path=document.path)
            for _, document in attachments
        ],
    )
