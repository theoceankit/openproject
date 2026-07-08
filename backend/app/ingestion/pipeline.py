import hashlib
import logging
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Document
from app.ingestion.parsers import parse_markdown, parse_pdf
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


async def ingest_file(db: AsyncSession, provider: ModelProvider, file_path: Path) -> dict:
    data = file_path.read_bytes()
    content_hash = compute_content_hash(data)
    doc_type = SUPPORTED_EXTENSIONS[file_path.suffix.lower()]
    path_str = str(file_path.resolve())

    existing = (await db.execute(select(Document).where(Document.path == path_str))).scalar_one_or_none()
    if existing and existing.content_hash == content_hash:
        logger.info("document unchanged: %s", path_str)
        return {"path": path_str, "status": "unchanged", "chunks": 0}

    sections = parse_markdown(data.decode("utf-8")) if doc_type == "markdown" else parse_pdf(file_path)

    if existing:
        document = existing
        document.content_hash = content_hash
        await db.execute(delete(Chunk).where(Chunk.document_id == document.id))
        status = "updated"
    else:
        document = Document(path=path_str, doc_type=doc_type, content_hash=content_hash)
        db.add(document)
        status = "ingested"

    await db.flush()

    embedding_inputs = [f"{s.section}\n\n{s.content}" if s.section else s.content for s in sections]
    embeddings = await provider.embed(embedding_inputs, call_site="ingestion") if sections else []
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

    await db.commit()
    logger.info("document %s: %s (%d chunks, document_id=%s)", status, path_str, len(sections), document.id)
    return {"path": path_str, "status": status, "chunks": len(sections)}
