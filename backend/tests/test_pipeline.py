from pathlib import Path

from sqlalchemy import select

from app.db.models import Document
from app.ingestion.pipeline import compute_content_hash, discover_files, ingest_path
from tests.test_chat import make_vector


class FakeProvider:
    async def embed(self, texts, *, call_site=None):
        return [make_vector() for _ in texts]


def test_discover_files_filters_to_md_mdx_and_pdf_recursively(tmp_path: Path):
    (tmp_path / "doc.md").write_text("# Doc")
    (tmp_path / "page.mdx").write_text("# Page")
    (tmp_path / "notes.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "ignore.txt").write_text("not relevant")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "nested.md").write_text("# Nested")

    files = discover_files(tmp_path)

    assert files == sorted(
        [tmp_path / "doc.md", tmp_path / "page.mdx", tmp_path / "notes.pdf", sub / "nested.md"]
    )


def test_discover_files_single_file(tmp_path: Path):
    md_file = tmp_path / "doc.md"
    md_file.write_text("# Doc")
    txt_file = tmp_path / "doc.txt"
    txt_file.write_text("not relevant")

    assert discover_files(md_file) == [md_file]
    assert discover_files(txt_file) == []


def test_compute_content_hash_is_stable_and_sensitive_to_content():
    assert compute_content_hash(b"hello") == compute_content_hash(b"hello")
    assert compute_content_hash(b"hello") != compute_content_hash(b"world")


async def test_ingest_path_continues_after_a_failing_file_and_reports_its_error(db_session, tmp_path: Path):
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe not valid utf-8")
    later = tmp_path / "later.md"
    later.write_text("# Later\n\nContent")

    results = await ingest_path(db_session, FakeProvider(), tmp_path)

    by_path = {r["path"]: r for r in results}
    bad_result = by_path[str(bad.resolve())]
    assert bad_result["status"] == "failed"
    assert bad_result["error"]
    later_result = by_path[str(later.resolve())]
    assert later_result["status"] == "ingested"

    documents = (await db_session.execute(select(Document))).scalars().all()
    assert {d.path for d in documents} == {str(later.resolve())}
