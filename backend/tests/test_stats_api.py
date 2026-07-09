import uuid

from httpx import ASGITransport, AsyncClient

from app.db.models import Chunk, Conversation, Document, ModelCall, Project
from app.db.session import get_db
from app.main import app


async def _request(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get("/stats")
    finally:
        app.dependency_overrides.pop(get_db, None)


def _document(*, origin: str) -> Document:
    return Document(
        path=f"/tmp/{uuid.uuid4()}.md",
        doc_type="markdown",
        content_hash=uuid.uuid4().hex,
        origin=origin,
    )


async def test_stats_are_zero_on_an_empty_database(db_session):
    response = await _request(db_session)

    assert response.status_code == 200
    assert response.json() == {
        "corpus": {"projects": 0, "documents": 0, "chunks": 0, "conversations": 0},
        "usage": {"model_calls": 0, "tokens": 0},
    }


async def test_corpus_counts_exclude_attachment_documents_and_their_chunks(db_session):
    db_session.add(Project(name="Apollo"))
    ingested = _document(origin="ingested")
    attachment = _document(origin="attachment")
    db_session.add_all([ingested, attachment])
    await db_session.flush()
    db_session.add_all(
        [
            Chunk(document_id=ingested.id, chunk_index=0, content="a"),
            Chunk(document_id=attachment.id, chunk_index=0, content="b"),
        ]
    )
    db_session.add(Conversation(title="hello"))
    await db_session.commit()

    response = await _request(db_session)

    body = response.json()["corpus"]
    assert body == {"projects": 1, "documents": 1, "chunks": 1, "conversations": 1}


async def test_usage_aggregates_model_calls_and_tokens(db_session):
    db_session.add_all(
        [
            ModelCall(operation="generate", call_site="chat", model="qwen2.5:14b-instruct", prompt_tokens=100, completion_tokens=20),
            ModelCall(operation="embed", call_site="retrieval", model="bge-m3", prompt_tokens=10, completion_tokens=None),
        ]
    )
    await db_session.commit()

    response = await _request(db_session)

    assert response.json()["usage"] == {"model_calls": 2, "tokens": 130}
