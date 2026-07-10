import hashlib
import logging
import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, ConversationAttachment, Document
from app.ingestion.parsers import parse_markdown, parse_pdf
from app.ingestion.storage import store_document_copy
from app.providers.base import ModelProvider

logger = logging.getLogger("app.ingestion")

SUPPORTED_EXTENSIONS = {".md": "markdown", ".mdx": "markdown", ".pdf": "pdf"}


def discover_files(root: Path) -> list[Path]:
    """Find supported files at a path: the file itself, or a recursive folder scan."""
    if root.is_file():
        return [root] if root.suffix.lower() in SUPPORTED_EXTENSIONS else []
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS)


def compute_content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def ingest_path(db: AsyncSession, provider: ModelProvider, root: Path) -> list[dict]:
    results = []
    for file_path in discover_files(root):
        try:
            result = await ingest_file(db, provider, file_path)
        except Exception as exc:
            await db.rollback()
            logger.exception("document failed: %s", file_path)
            result = {"path": str(file_path.resolve()), "status": "failed", "chunks": 0, "error": str(exc)}
        results.append(result)
    return results


async def _write_document_chunks(
    db: AsyncSession, provider: ModelProvider, file_path: Path, *, origin: str, call_site: str
) -> tuple[Document, str, int]:
    """Parse, chunk, and embed a file into a Document + Chunks. Flushes but does not commit."""
    data = file_path.read_bytes()
    content_hash = compute_content_hash(data)
    doc_type = SUPPORTED_EXTENSIONS[file_path.suffix.lower()]
    path_str = str(file_path.resolve())

    existing = (await db.execute(select(Document).where(Document.path == path_str))).scalar_one_or_none()
    if existing and existing.content_hash == content_hash:
        logger.info("document unchanged: %s", path_str)
        if existing.stored_path is None:
            existing.stored_path = store_document_copy(existing.id, file_path.name, data)
        return existing, "unchanged", 0

    sections = parse_markdown(data.decode("utf-8")) if doc_type == "markdown" else parse_pdf(file_path)

    if existing:
        document = existing
        document.content_hash = content_hash
        await db.execute(delete(Chunk).where(Chunk.document_id == document.id))
        status = "updated"
    else:
        document = Document(path=path_str, doc_type=doc_type, content_hash=content_hash, origin=origin)
        db.add(document)
        status = "ingested"

    await db.flush()

    document.stored_path = store_document_copy(document.id, file_path.name, data)

    embedding_inputs = [f"{s.section}\n\n{s.content}" if s.section else s.content for s in sections]
    embeddings = await provider.embed(embedding_inputs, call_site=call_site) if sections else []
    if len(embeddings) != len(sections):
        raise RuntimeError(f"embed() returned {len(embeddings)} vectors for {len(sections)} inputs")
    for index, (section, embedding) in enumerate(zip(sections, embeddings)):
        db.add(
            Chunk(
                document_id=document.id,
                chunk_index=index,
                content=section.content,
                section=section.section,
                embedding=embedding,
            )
        )

    return document, status, len(sections)


async def ingest_file(db: AsyncSession, provider: ModelProvider, file_path: Path) -> dict:
    document, status, chunks = await _write_document_chunks(
        db, provider, file_path, origin="ingested", call_site="ingestion"
    )
    await db.commit()
    logger.info("document %s: %s (%d chunks, document_id=%s)", status, str(document.path), chunks, document.id)
    return {"path": document.path, "status": status, "chunks": chunks}


async def ingest_attachments(
    db: AsyncSession, provider: ModelProvider, conversation_id: uuid.UUID, paths: list[Path]
) -> list[dict]:
    """Stage files as one-off context for a conversation (origin="attachment"), skipping extraction."""
    results = []
    for file_path in paths:
        try:
            result = await ingest_attachment(db, provider, conversation_id, file_path)
        except Exception as exc:
            await db.rollback()
            logger.exception("attachment failed: %s", file_path)
            result = {
                "path": str(file_path.resolve()) if file_path.exists() else str(file_path),
                "filename": file_path.name,
                "status": "failed",
                "chunks": 0,
                "document_id": None,
                "error": str(exc),
            }
        results.append(result)
    return results


async def ingest_attachment(
    db: AsyncSession, provider: ModelProvider, conversation_id: uuid.UUID, file_path: Path
) -> dict:
    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return {
            "path": str(file_path),
            "filename": file_path.name,
            "status": "failed",
            "chunks": 0,
            "document_id": None,
            "error": f"Unsupported file type: {file_path.suffix}",
        }
    if not file_path.exists():
        return {
            "path": str(file_path),
            "filename": file_path.name,
            "status": "failed",
            "chunks": 0,
            "document_id": None,
            "error": "File not found",
        }

    document, status, chunks = await _write_document_chunks(
        db, provider, file_path, origin="attachment", call_site="attachment"
    )

    existing_link = (
        await db.execute(
            select(ConversationAttachment).where(
                ConversationAttachment.conversation_id == conversation_id,
                ConversationAttachment.document_id == document.id,
            )
        )
    ).scalar_one_or_none()
    if existing_link is None:
        db.add(ConversationAttachment(conversation_id=conversation_id, document_id=document.id))

    await db.commit()
    logger.info(
        "attachment %s: %s (conversation=%s, document_id=%s)", document.path, status, conversation_id, document.id
    )
    return {
        "path": document.path,
        "filename": file_path.name,
        "status": status,
        "chunks": chunks,
        "document_id": str(document.id),
        "error": None,
    }
