"""Tests for conversation title generation in the chat pipeline (see CLAUDE.md's
"conversation history" feature spec: `answer_question()` should generate a short title
for a conversation on its first turn only, and never overwrite it afterwards).

These tests define, as part of the contract under test, that `answer_question()`
distinguishes the title-generation provider call from the query-rewrite/fact-update/
chat-answer calls via `call_site="title"` (mirroring the existing call sites "query_rewrite",
"fact_update", and "chat" already used elsewhere in the pipeline). `TitleFakeProvider` below
extends the chat tests' `FakeProvider` to respond distinctly to that call site.
"""

from httpx import ASGITransport, AsyncClient

from app.chat.pipeline import answer_question
from app.chat.prompts import FACT_UPDATE_SYSTEM_PROMPT, QUERY_REWRITE_SYSTEM_PROMPT
from app.db.models import Conversation
from app.db.session import get_db
from app.main import app
from app.providers.factory import get_provider
from tests.test_chat import FakeProvider, make_document_with_chunk, make_vector


class TitleFakeProvider(FakeProvider):
    """A FakeProvider that also answers the title-generation call (call_site="title")."""

    def __init__(self, *args, title="Untitled", **kwargs):
        super().__init__(*args, **kwargs)
        self._title = title

    async def generate(self, prompt, *, system=None, format=None, model=None, call_site=None):
        self.generate_calls.append({"prompt": prompt, "system": system, "format": format, "call_site": call_site})
        if call_site == "title":
            return self._title
        if system == QUERY_REWRITE_SYSTEM_PROMPT:
            return self._rewritten
        if system == FACT_UPDATE_SYSTEM_PROMPT:
            return self.fact_update
        return self._answer


async def test_first_turn_generates_and_persists_a_title(db_session):
    """A brand-new conversation's first turn asks the provider for a title and stores it
    on both the Conversation row and the returned ChatAnswer."""
    await make_document_with_chunk(db_session)
    provider = TitleFakeProvider(
        query_embedding=make_vector((0, 1.0)),
        answer="A SKU is a Stock Keeping Unit.",
        title="SKU Terminology",
    )

    result = await answer_question(db_session, provider, "What is a SKU?")

    assert result.title == "SKU Terminology"
    conversation = await db_session.get(Conversation, result.conversation_id)
    assert conversation.title == "SKU Terminology"

    title_calls = [c for c in provider.generate_calls if c["call_site"] == "title"]
    assert len(title_calls) == 1


async def test_generated_title_is_stripped_of_surrounding_whitespace(db_session):
    """Providers are free to pad generated text; the stored title should be trimmed,
    mirroring how the query-rewrite result is `.strip()`-ed elsewhere in the pipeline."""
    await make_document_with_chunk(db_session)
    provider = TitleFakeProvider(
        query_embedding=make_vector((0, 1.0)),
        answer="Answer.",
        title="  SKU Terminology  \n",
    )

    result = await answer_question(db_session, provider, "What is a SKU?")

    assert result.title == "SKU Terminology"


async def test_second_turn_does_not_regenerate_title(db_session):
    """Once a conversation has a title, later turns must not overwrite it or call the
    provider for a new one."""
    await make_document_with_chunk(db_session)
    provider_one = TitleFakeProvider(
        query_embedding=make_vector((0, 1.0)), answer="First answer.", title="Original Title"
    )
    first = await answer_question(db_session, provider_one, "What is a SKU?")
    conversation = await db_session.get(Conversation, first.conversation_id)
    assert conversation.title == "Original Title"

    provider_two = TitleFakeProvider(
        query_embedding=make_vector((0, 1.0)), answer="Second answer.", title="Should Not Be Used"
    )
    second = await answer_question(db_session, provider_two, "Tell me more", conversation)

    assert second.title == "Original Title"
    await db_session.refresh(conversation)
    assert conversation.title == "Original Title"
    assert not any(c["call_site"] == "title" for c in provider_two.generate_calls)


async def test_chat_endpoint_returns_title_on_first_message(db_session):
    """The /chat response mirrors ChatAnswer's other fields (sources, pending_fact,
    attachments), so it should also surface the generated title."""
    provider = TitleFakeProvider(query_embedding=make_vector((0, 1.0)), answer="Hello!", title="Greeting Chat")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/chat", json={"message": "Hello"})
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_provider, None)

    assert response.status_code == 200
    assert response.json()["title"] == "Greeting Chat"


async def test_chat_endpoint_keeps_existing_title_on_second_message(db_session):
    provider_one = TitleFakeProvider(query_embedding=make_vector((0, 1.0)), answer="Hello!", title="Greeting Chat")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider] = lambda: provider_one
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post("/chat", json={"message": "Hello"})
            conversation_id = first.json()["conversation_id"]

            provider_two = TitleFakeProvider(
                query_embedding=make_vector((0, 1.0)), answer="Hi again!", title="Different Title"
            )
            app.dependency_overrides[get_provider] = lambda: provider_two
            second = await client.post(
                "/chat", json={"message": "Again", "conversation_id": conversation_id}
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_provider, None)

    assert second.status_code == 200
    assert second.json()["title"] == "Greeting Chat"
