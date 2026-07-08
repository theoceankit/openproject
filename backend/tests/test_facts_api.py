from httpx import ASGITransport, AsyncClient

from app.chat.memory import record_fact
from app.db.models import Conversation, Fact, Message
from app.db.session import get_db
from app.extraction.schemas import FactUpdateResult
from app.main import app


async def make_pending_fact(db_session) -> Fact:
    conversation = Conversation()
    db_session.add(conversation)
    await db_session.flush()
    message = Message(conversation_id=conversation.id, role="user", content="The SLA changed to 80%")
    db_session.add(message)
    await db_session.flush()

    update = FactUpdateResult(
        should_record=True,
        project="",
        subject="Storefront Redesign SLA",
        predicate="value",
        object="",
        value="80%",
    )
    fact = await record_fact(db_session, update, source_message_id=message.id)
    await db_session.commit()
    return fact


async def test_list_and_confirm_pending_fact(db_session):
    fact = await make_pending_fact(db_session)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            list_response = await client.get("/facts/pending")
            assert list_response.status_code == 200
            body = list_response.json()
            assert body["total"] == 1
            [item] = body["items"]
            assert item["subject"] == "Storefront Redesign SLA"
            assert item["predicate"] == "value"
            assert item["object"] == "80%"

            resolve_response = await client.post(f"/facts/{item['id']}/resolve", json={"confirm": True})
            assert resolve_response.status_code == 200
            assert resolve_response.json()["status"] == "confirmed"

            second_response = await client.get("/facts/pending")
            assert second_response.json() == {"items": [], "total": 0}
    finally:
        app.dependency_overrides.pop(get_db, None)

    await db_session.refresh(fact)
    assert fact.status == "confirmed"


async def test_reject_pending_fact(db_session):
    fact = await make_pending_fact(db_session)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resolve_response = await client.post(f"/facts/{fact.id}/resolve", json={"confirm": False})
            assert resolve_response.status_code == 200
            assert resolve_response.json()["status"] == "rejected"
    finally:
        app.dependency_overrides.pop(get_db, None)

    await db_session.refresh(fact)
    assert fact.status == "rejected"


async def test_resolve_unknown_fact_returns_404(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/facts/00000000-0000-0000-0000-000000000000/resolve", json={"confirm": True}
            )
            assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_resolve_already_resolved_fact_returns_400(db_session):
    fact = await make_pending_fact(db_session)
    fact.status = "confirmed"
    await db_session.commit()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/facts/{fact.id}/resolve", json={"confirm": True})
            assert response.status_code == 400
    finally:
        app.dependency_overrides.pop(get_db, None)
