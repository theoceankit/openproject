from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.models import Chunk, Document
from app.db.session import get_db
from app.extraction.schemas import ExtractionResult, ProjectResolutionResult
from app.main import app
from app.providers.factory import get_provider
from tests.test_chat import make_vector


class FailingExtractionProvider:
    async def generate(self, prompt, *, system=None, format=None, model=None, call_site=None):
        raise RuntimeError("ollama unreachable")

    async def embed(self, texts, *, call_site=None):
        return [make_vector() for _ in texts]


async def test_ingest_reports_per_file_extraction_errors_without_failing_the_whole_batch(
    db_session, tmp_path: Path
):
    (tmp_path / "a.md").write_text("# A\n\nContent A")
    (tmp_path / "b.md").write_text("# B\n\nContent B")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider] = lambda: FailingExtractionProvider()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/documents/ingest", json={"path": str(tmp_path)})
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_provider, None)

    assert response.status_code == 200
    results = response.json()
    assert len(results) == 2
    for result in results:
        assert result["status"] == "ingested"
        assert result["error"]
        assert result["project_id"] is None


class ExtractionProvider:
    """Answers extraction calls with a fixed response, and any project-resolution call
    (triggered when the DB already has other projects) with a deterministic "new"."""

    def __init__(self, response: str):
        self._response = response

    async def generate(self, prompt, *, system=None, format=None, model=None, call_site=None):
        if call_site == "project_resolution":
            return ProjectResolutionResult(outcome="new").model_dump_json()
        return self._response

    async def embed(self, texts, *, call_site=None):
        return [make_vector() for _ in texts]


EXTRACTION_RESPONSE = ExtractionResult.model_validate(
    {
        "project": {"name": "Storefront", "description": "Online shop"},
        "people": [],
        "terms": [],
        "teams": [],
        "relations": [],
    }
).model_dump_json()


async def make_attachment_document(db_session) -> Document:
    document = Document(path="/tmp/attached.md", doc_type="markdown", content_hash="abc123", origin="attachment")
    db_session.add(document)
    await db_session.flush()
    db_session.add(Chunk(document_id=document.id, chunk_index=0, content="Some content", section="Overview"))
    await db_session.flush()
    return document


async def test_promote_moves_an_attachment_into_the_corpus(db_session):
    document = await make_attachment_document(db_session)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider] = lambda: ExtractionProvider(EXTRACTION_RESPONSE)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/documents/{document.id}/promote")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_provider, None)

    assert response.status_code == 200
    body = response.json()
    assert body["project_resolution"] in ("new", "match")
    assert body["project_id"]

    refreshed = (await db_session.execute(select(Document).where(Document.id == document.id))).scalar_one()
    assert refreshed.origin == "ingested"
    assert refreshed.project_id is not None


async def test_promote_unknown_document_returns_404(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider] = lambda: ExtractionProvider(EXTRACTION_RESPONSE)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/documents/00000000-0000-0000-0000-000000000000/promote")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_provider, None)

    assert response.status_code == 404


async def test_promote_document_already_in_corpus_returns_400(db_session):
    document = Document(path="/tmp/ingested.md", doc_type="markdown", content_hash="abc123", origin="ingested")
    db_session.add(document)
    await db_session.flush()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider] = lambda: ExtractionProvider(EXTRACTION_RESPONSE)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/documents/{document.id}/promote")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_provider, None)

    assert response.status_code == 400
