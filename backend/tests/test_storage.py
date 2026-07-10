"""Tests for app.ingestion.storage.store_document_copy (does not exist yet).

store_document_copy(document_id, original_filename, data) writes a durable copy of an
ingested/attached file's bytes under settings.storage_dir, keyed by Document.id, so the
frontend can later open the actual file. See documentation/docs/architecture and the
technical spec for the full contract; this module is the test surface for it.
"""

import uuid
from pathlib import Path

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _redirect_storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point settings.storage_dir at a fresh tmp_path for every test in this module."""
    storage_root = tmp_path / "storage-root"
    monkeypatch.setattr(settings, "storage_dir", str(storage_root))
    return storage_root


def test_store_document_copy_writes_bytes_under_storage_dir_by_document_id(_redirect_storage_dir: Path):
    from app.ingestion.storage import store_document_copy

    document_id = uuid.uuid4()
    data = b"# Notes\n\nHello world"

    result = store_document_copy(document_id, "notes.md", data)

    dest = Path(result)
    assert dest.exists()
    assert dest.read_bytes() == data
    assert dest.name == "notes.md"
    assert dest.parent.name == str(document_id)
    assert dest.parent.parent == _redirect_storage_dir.resolve()


def test_store_document_copy_returns_resolved_absolute_path_string(_redirect_storage_dir: Path):
    from app.ingestion.storage import store_document_copy

    document_id = uuid.uuid4()

    result = store_document_copy(document_id, "notes.md", b"content")

    assert isinstance(result, str)
    resolved = Path(result)
    assert resolved.is_absolute()
    assert str(resolved) == str(resolved.resolve())


def test_store_document_copy_creates_storage_dir_if_missing(_redirect_storage_dir: Path):
    from app.ingestion.storage import store_document_copy

    assert not _redirect_storage_dir.exists()
    document_id = uuid.uuid4()

    result = store_document_copy(document_id, "notes.md", b"content")

    assert Path(result).exists()


def test_store_document_copy_leaves_no_tmp_file_behind(_redirect_storage_dir: Path):
    from app.ingestion.storage import store_document_copy

    document_id = uuid.uuid4()

    result = store_document_copy(document_id, "notes.md", b"content")

    doc_dir = Path(result).parent
    leftovers = [p.name for p in doc_dir.iterdir() if p.name != "notes.md"]
    assert leftovers == []


def test_store_document_copy_overwrites_idempotently_on_repeat_call(_redirect_storage_dir: Path):
    from app.ingestion.storage import store_document_copy

    document_id = uuid.uuid4()

    first_result = store_document_copy(document_id, "notes.md", b"first version")
    second_result = store_document_copy(document_id, "notes.md", b"second version, different length")

    assert first_result == second_result
    dest = Path(second_result)
    assert dest.read_bytes() == b"second version, different length"

    doc_dir = dest.parent
    files = list(doc_dir.iterdir())
    assert len(files) == 1
    assert files[0].name == "notes.md"


def test_store_document_copy_isolates_same_filename_across_different_document_ids(_redirect_storage_dir: Path):
    from app.ingestion.storage import store_document_copy

    first_id = uuid.uuid4()
    second_id = uuid.uuid4()

    first_result = store_document_copy(first_id, "notes.md", b"belongs to first")
    second_result = store_document_copy(second_id, "notes.md", b"belongs to second")

    assert first_result != second_result
    assert Path(first_result).read_bytes() == b"belongs to first"
    assert Path(second_result).read_bytes() == b"belongs to second"
    assert Path(first_result).parent.name == str(first_id)
    assert Path(second_result).parent.name == str(second_id)
