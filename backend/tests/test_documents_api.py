from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.db.session import get_db
from app.main import app
from app.providers.factory import get_provider
from tests.test_chat import make_vector


class FailingExtractionProvider:
    async def generate(self, prompt, *, system=None, format=None, call_site=None):
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
