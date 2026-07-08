from pathlib import Path

from sqlalchemy import select

from app.db.models import Conversation, ConversationAttachment, Document
from app.ingestion.pipeline import compute_content_hash, discover_files, ingest_attachment, ingest_attachments, ingest_path
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


async def make_conversation(db_session) -> Conversation:
    conversation = Conversation()
    db_session.add(conversation)
    await db_session.flush()
    return conversation


async def test_ingest_attachment_sets_attachment_origin_and_links_conversation(db_session, tmp_path: Path):
    conversation = await make_conversation(db_session)
    doc_file = tmp_path / "notes.md"
    doc_file.write_text("# Notes\n\nSome content")

    result = await ingest_attachment(db_session, FakeProvider(), conversation.id, doc_file)

    assert result["status"] == "ingested"
    assert result["chunks"] == 1
    document = (await db_session.execute(select(Document).where(Document.path == str(doc_file.resolve())))).scalar_one()
    assert document.origin == "attachment"
    assert document.project_id is None

    link = (
        await db_session.execute(
            select(ConversationAttachment).where(ConversationAttachment.conversation_id == conversation.id)
        )
    ).scalar_one()
    assert link.document_id == document.id


async def test_ingest_attachment_reuses_existing_link_on_repeat_attach(db_session, tmp_path: Path):
    conversation = await make_conversation(db_session)
    doc_file = tmp_path / "notes.md"
    doc_file.write_text("# Notes\n\nSome content")

    await ingest_attachment(db_session, FakeProvider(), conversation.id, doc_file)
    await ingest_attachment(db_session, FakeProvider(), conversation.id, doc_file)

    links = (
        await db_session.execute(
            select(ConversationAttachment).where(ConversationAttachment.conversation_id == conversation.id)
        )
    ).scalars().all()
    assert len(links) == 1


async def test_ingest_attachment_rejects_unsupported_extension(db_session, tmp_path: Path):
    conversation = await make_conversation(db_session)
    doc_file = tmp_path / "notes.txt"
    doc_file.write_text("plain text")

    result = await ingest_attachment(db_session, FakeProvider(), conversation.id, doc_file)

    assert result["status"] == "failed"
    assert "Unsupported" in result["error"]


async def test_ingest_attachments_continues_after_a_missing_file(db_session, tmp_path: Path):
    conversation = await make_conversation(db_session)
    missing = tmp_path / "missing.md"
    present = tmp_path / "present.md"
    present.write_text("# Present\n\nContent")

    results = await ingest_attachments(db_session, FakeProvider(), conversation.id, [missing, present])

    by_filename = {r["filename"]: r for r in results}
    assert by_filename["missing.md"]["status"] == "failed"
    assert by_filename["present.md"]["status"] == "ingested"
