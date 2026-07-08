from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Document, Project
from app.providers.base import ModelProvider


@dataclass
class RetrievedChunk:
    """A chunk retrieved for a query, with a reference back to its source."""

    document_path: str
    section: str | None
    content: str
    project_name: str | None = None


async def search_chunks(db: AsyncSession, provider: ModelProvider, query: str, limit: int) -> list[RetrievedChunk]:
    """Find the chunks most relevant to a query, by embedding similarity."""
    embeddings = await provider.embed([query], call_site="retrieval")
    query_embedding = embeddings[0]

    rows = (
        await db.execute(
            select(Chunk, Document, Project)
            .join(Document, Chunk.document_id == Document.id)
            .outerjoin(Project, Document.project_id == Project.id)
            .order_by(Chunk.embedding.cosine_distance(query_embedding))
            .limit(limit)
        )
    ).all()

    return [
        RetrievedChunk(
            document_path=document.path,
            section=chunk.section,
            content=chunk.content,
            project_name=project.name if project is not None else None,
        )
        for chunk, document, project in rows
    ]
