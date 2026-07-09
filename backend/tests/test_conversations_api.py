"""Tests for the conversation-history listing/detail endpoints (see CLAUDE.md's
"conversation history" feature spec): `GET /conversations` (paginated summaries, most
recently active first) and `GET /conversations/{id}` (full detail).

Field names below (`preview`, `message_count`, `updated_at`, `messages`, `attachments`,
`path`/`filename`/`document_id`) are this test file's chosen, reasonable rendering of the
spec's black-box contract; they are not tied to any particular internal implementation.
"""

from datetime import datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient

from app.db.models import Conversation, ConversationAttachment, Document, Message
from app.db.session import get_db
from app.main import app

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


async def make_conversation(db_session, *, created_at, title=None) -> Conversation:
    conversation = Conversation(created_at=created_at, updated_at=created_at, title=title)
    db_session.add(conversation)
    await db_session.flush()
    return conversation


async def add_message(db_session, conversation, *, role, content, created_at, sources=None) -> Message:
    message = Message(
        conversation_id=conversation.id,
        role=role,
        content=content,
        sources=sources,
        created_at=created_at,
        updated_at=created_at,
    )
    db_session.add(message)
    await db_session.flush()
    return message


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def test_list_conversations_orders_by_latest_message_not_created_at(db_session):
    """A conversation created long ago but active a minute ago should outrank one created
    an hour ago whose last message is five days stale."""
    old_conversation = await make_conversation(db_session, created_at=NOW - timedelta(days=10), title="Old topic")
    await add_message(db_session, old_conversation, role="user", content="Ping", created_at=NOW - timedelta(minutes=1))

    newer_conversation = await make_conversation(db_session, created_at=NOW - timedelta(hours=1), title="Newer topic")
    await add_message(
        db_session, newer_conversation, role="user", content="Stale question", created_at=NOW - timedelta(days=5)
    )

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/conversations")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    ids = [item["id"] for item in body["items"]]
    assert ids == [str(old_conversation.id), str(newer_conversation.id)]


async def test_conversation_summary_includes_title_preview_and_message_count(db_session):
    conversation = await make_conversation(db_session, created_at=NOW, title="Storefront SLA")
    await add_message(db_session, conversation, role="user", content="What is the SLA?", created_at=NOW)
    await add_message(
        db_session,
        conversation,
        role="assistant",
        content="The SLA is 80% uptime.",
        created_at=NOW + timedelta(seconds=1),
    )

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/conversations")
    finally:
        app.dependency_overrides.pop(get_db, None)

    [item] = response.json()["items"]
    assert item["title"] == "Storefront SLA"
    assert item["message_count"] == 2
    assert "80% uptime" in item["preview"]


async def test_conversation_summary_title_is_null_when_not_yet_generated(db_session):
    conversation = await make_conversation(db_session, created_at=NOW, title=None)
    await add_message(db_session, conversation, role="user", content="Hello", created_at=NOW)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/conversations")
    finally:
        app.dependency_overrides.pop(get_db, None)

    [item] = response.json()["items"]
    assert item["title"] is None


async def test_conversation_summary_updated_at_reflects_last_message_not_creation(db_session):
    conversation = await make_conversation(db_session, created_at=NOW - timedelta(days=1), title="Topic")
    await add_message(db_session, conversation, role="user", content="Hi", created_at=NOW - timedelta(hours=2))
    last_message_at = NOW - timedelta(minutes=5)
    await add_message(db_session, conversation, role="assistant", content="Hello back", created_at=last_message_at)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/conversations")
    finally:
        app.dependency_overrides.pop(get_db, None)

    [item] = response.json()["items"]
    returned = parse_dt(item["updated_at"])
    assert abs((returned - last_message_at).total_seconds()) < 2


async def test_list_conversations_paginates_with_limit_and_offset(db_session):
    conversations = []
    for i in range(5):
        conversation = await make_conversation(db_session, created_at=NOW + timedelta(minutes=i), title=f"Topic {i}")
        await add_message(
            db_session, conversation, role="user", content=f"msg {i}", created_at=NOW + timedelta(minutes=i)
        )
        conversations.append(conversation)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first_page = await client.get("/conversations", params={"limit": 2, "offset": 0})
            second_page = await client.get("/conversations", params={"limit": 2, "offset": 2})
    finally:
        app.dependency_overrides.pop(get_db, None)

    first_body = first_page.json()
    second_body = second_page.json()
    assert first_body["total"] == 5
    assert second_body["total"] == 5
    # Most recently active first: Topic 4 (latest) then Topic 3, etc.
    assert [c["title"] for c in first_body["items"]] == ["Topic 4", "Topic 3"]
    assert [c["title"] for c in second_body["items"]] == ["Topic 2", "Topic 1"]


async def test_get_conversation_detail_returns_messages_in_order_with_sources(db_session):
    conversation = await make_conversation(db_session, created_at=NOW, title="Storefront SLA")
    await add_message(db_session, conversation, role="user", content="What is the SLA?", created_at=NOW)
    await add_message(
        db_session,
        conversation,
        role="assistant",
        content="It's 80%.",
        created_at=NOW + timedelta(seconds=1),
        sources=[{"document_path": "/docs/sla.md", "section": "SLA", "project_name": None}],
    )

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/conversations/{conversation.id}")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(conversation.id)
    assert body["title"] == "Storefront SLA"

    messages = body["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "What is the SLA?"
    assert messages[1]["content"] == "It's 80%."
    assert messages[1]["sources"] == [{"document_path": "/docs/sla.md", "section": "SLA", "project_name": None}]
    assert messages[0]["sources"] is None


async def test_get_conversation_detail_includes_attachments(db_session):
    conversation = await make_conversation(db_session, created_at=NOW, title="With attachment")
    await add_message(db_session, conversation, role="user", content="See attached", created_at=NOW)

    document = Document(path="/tmp/notes.md", doc_type="markdown", content_hash="abc123", origin="attachment")
    db_session.add(document)
    await db_session.flush()
    db_session.add(ConversationAttachment(conversation_id=conversation.id, document_id=document.id))
    await db_session.flush()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/conversations/{conversation.id}")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    attachments = response.json()["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["document_id"] == str(document.id)
    assert attachments[0]["path"] == "/tmp/notes.md"


async def test_get_conversation_detail_returns_empty_attachments_when_none(db_session):
    conversation = await make_conversation(db_session, created_at=NOW, title="No attachments")
    await add_message(db_session, conversation, role="user", content="Hello", created_at=NOW)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/conversations/{conversation.id}")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.json()["attachments"] == []


async def test_get_conversation_detail_returns_404_for_unknown_id(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/conversations/00000000-0000-0000-0000-000000000000")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 404


async def test_get_conversation_detail_returns_400_for_malformed_id(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/conversations/not-a-uuid")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 400
