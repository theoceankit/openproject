from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.db.models import Document, Message
from app.db.session import get_db
from app.main import app
from app.providers.factory import get_provider
from sqlalchemy import select
from tests.test_chat import FakeProvider, make_vector


async def test_chat_persists_and_continues_conversation(db_session):
    provider = FakeProvider(query_embedding=make_vector((0, 1.0)), answer="Hello!")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post("/chat", json={"message": "Hello"})
            assert first.status_code == 200
            conversation_id = first.json()["conversation_id"]

            second = await client.post("/chat", json={"message": "Again", "conversation_id": conversation_id})
            assert second.status_code == 200
            assert second.json()["conversation_id"] == conversation_id
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_provider, None)

    messages = (
        await db_session.execute(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
        )
    ).scalars().all()
    assert len(messages) == 4


async def test_chat_response_includes_pending_fact_when_recorded(db_session):
    fact_update = (
        '{"should_record": true, "project": "", "subject": "Storefront Redesign SLA", '
        '"predicate": "value", "object": "", "value": "80%"}'
    )
    provider = FakeProvider(query_embedding=make_vector((0, 1.0)), answer="Noted.", fact_update=fact_update)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/chat", json={"message": "The SLA changed to 80%"})
            assert response.status_code == 200
            pending_fact = response.json()["pending_fact"]
            assert pending_fact["subject"] == "Storefront Redesign SLA"
            assert pending_fact["predicate"] == "value"
            assert pending_fact["object"] == "80%"
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_provider, None)


async def test_chat_response_pending_fact_is_null_without_a_fact(db_session):
    provider = FakeProvider(query_embedding=make_vector((0, 1.0)), answer="Hello!")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/chat", json={"message": "Hello"})
            assert response.status_code == 200
            assert response.json()["pending_fact"] is None
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_provider, None)


async def test_chat_with_unknown_conversation_id_returns_404(db_session):
    provider = FakeProvider(query_embedding=make_vector((0, 1.0)), answer="Hello!")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/chat",
                json={"message": "Hello", "conversation_id": "00000000-0000-0000-0000-000000000000"},
            )
            assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_provider, None)


async def test_chat_with_attachment_stages_it_as_a_conversation_scoped_document(db_session, tmp_path: Path):
    doc_file = tmp_path / "notes.md"
    doc_file.write_text("# Notes\n\nSome content")
    provider = FakeProvider(query_embedding=make_vector((0, 1.0)), answer="Hello!")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/chat", json={"message": "What's in the file?", "attachments": [str(doc_file)]}
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_provider, None)

    assert response.status_code == 200
    body = response.json()
    assert len(body["attachments"]) == 1
    assert body["attachments"][0]["status"] == "ingested"
    assert body["attachments"][0]["document_id"]

    document = (
        await db_session.execute(select(Document).where(Document.path == str(doc_file.resolve())))
    ).scalar_one()
    assert document.origin == "attachment"
    assert document.project_id is None


async def test_chat_second_message_still_sees_earlier_attachment(db_session, tmp_path: Path):
    doc_file = tmp_path / "notes.md"
    doc_file.write_text("# Notes\n\nSome content")
    provider = FakeProvider(query_embedding=make_vector((0, 1.0)), answer="Hello!")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post(
                "/chat", json={"message": "What's in the file?", "attachments": [str(doc_file)]}
            )
            conversation_id = first.json()["conversation_id"]

            second = await client.post(
                "/chat", json={"message": "Tell me more", "conversation_id": conversation_id}
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_provider, None)

    assert second.status_code == 200
    sources = second.json()["sources"]
    assert any(s["is_attachment"] and s["document_path"] == str(doc_file.resolve()) for s in sources)


async def test_chat_with_malformed_conversation_id_returns_400(db_session):
    provider = FakeProvider(query_embedding=make_vector((0, 1.0)), answer="Hello!")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/chat", json={"message": "Hello", "conversation_id": "not-a-uuid"})
            assert response.status_code == 400
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_provider, None)
