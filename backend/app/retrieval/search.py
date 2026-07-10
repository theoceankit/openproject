import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, ConversationAttachment, Document, Project
from app.providers.base import ModelProvider


@dataclass
class RetrievedChunk:
    """A chunk retrieved for a query, with a reference back to its source."""

    document_path: str
    section: str | None
    content: str
    document_id: uuid.UUID
    stored_path: str | None
    project_name: str | None = None
    is_attachment: bool = False


async def search_chunks(db: AsyncSession, provider: ModelProvider, query: str, limit: int) -> list[RetrievedChunk]:
    """Find the chunks most relevant to a query, by embedding similarity, across the permanent corpus."""
    embeddings = await provider.embed([query], call_site="retrieval")
    query_embedding = embeddings[0]

    rows = (
        await db.execute(
            select(Chunk, Document, Project)
            .join(Document, Chunk.document_id == Document.id)
            .outerjoin(Project, Document.project_id == Project.id)
            .where(Document.origin != "attachment")
            .order_by(Chunk.embedding.cosine_distance(query_embedding))
            .limit(limit)
        )
    ).all()

    return [
        RetrievedChunk(
            document_path=document.path,
            section=chunk.section,
            content=chunk.content,
            document_id=document.id,
            stored_path=document.stored_path,
            project_name=project.name if project is not None else None,
        )
        for chunk, document, project in rows
    ]


async def search_attachment_chunks(
    db: AsyncSession, provider: ModelProvider, conversation_id: uuid.UUID, query: str, limit: int
) -> list[RetrievedChunk]:
    """Find the chunks most relevant to a query among files attached to this conversation."""
    embeddings = await provider.embed([query], call_site="attachment_retrieval")
    query_embedding = embeddings[0]

    rows = (
        await db.execute(
            select(Chunk, Document)
            .join(Document, Chunk.document_id == Document.id)
            .join(ConversationAttachment, ConversationAttachment.document_id == Document.id)
            .where(ConversationAttachment.conversation_id == conversation_id)
            .order_by(Chunk.embedding.cosine_distance(query_embedding))
            .limit(limit)
        )
    ).all()

    return [
        RetrievedChunk(
            document_path=document.path,
            section=chunk.section,
            content=chunk.content,
            document_id=document.id,
            stored_path=document.stored_path,
            is_attachment=True,
        )
        for chunk, document in rows
    ]
