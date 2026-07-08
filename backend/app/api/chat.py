import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.facts import PendingFactOut
from app.chat.pipeline import answer_question
from app.db.models import Conversation
from app.db.session import get_db
from app.providers.base import ModelProvider
from app.providers.factory import get_provider

router = APIRouter(prefix="/chat")


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ChatSource(BaseModel):
    document_path: str
    section: str | None = None
    project_name: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    sources: list[ChatSource]
    pending_fact: PendingFactOut | None = None


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    provider: ModelProvider = Depends(get_provider),
) -> ChatResponse:
    conversation: Conversation | None = None
    if request.conversation_id is not None:
        try:
            conversation_id = uuid.UUID(request.conversation_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid conversation id")
        conversation = await db.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    outcome = await answer_question(db, provider, request.message, conversation)
    return ChatResponse(
        conversation_id=str(outcome.conversation_id),
        answer=outcome.answer,
        sources=[
            ChatSource(document_path=s.document_path, section=s.section, project_name=s.project_name)
            for s in outcome.sources
        ],
        pending_fact=PendingFactOut(**outcome.pending_fact) if outcome.pending_fact else None,
    )
