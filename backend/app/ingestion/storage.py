import uuid
from pathlib import Path

from app.core.config import settings


def store_document_copy(document_id: uuid.UUID, original_filename: str, data: bytes) -> str:
    """Write a durable copy of an ingested/attached file's bytes, keyed by Document.id."""
    doc_dir = Path(settings.storage_dir) / str(document_id)
    doc_dir.mkdir(parents=True, exist_ok=True)

    dest = doc_dir / original_filename
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)

    return str(dest.resolve())
