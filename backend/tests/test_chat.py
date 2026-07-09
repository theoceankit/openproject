from sqlalchemy import select

from app.chat.pipeline import _truncate_history, answer_question
from app.chat.prompts import (
    CHAT_SYSTEM_PROMPT,
    FACT_UPDATE_SYSTEM_PROMPT,
    QUERY_REWRITE_SYSTEM_PROMPT,
    HistoryTurn,
    build_chat_prompt,
    build_fact_update_prompt,
    build_query_rewrite_prompt,
)
from app.core.config import settings
from app.db.models import Chunk, Conversation, Document, Fact, Message
from app.retrieval.search import RetrievedChunk


def make_vector(*nonzero: tuple[int, float]) -> list[float]:
    vector = [0.0] * settings.embedding_dim
    for index, value in nonzero:
        vector[index] = value
    return vector


class FakeProvider:
    def __init__(
        self,
        query_embedding: list[float],
        answer: str,
        rewritten: str = "",
        fact_update: str = '{"should_record": false}',
    ):
        self._query_embedding = query_embedding
        self._answer = answer
        self._rewritten = rewritten
        self.fact_update = fact_update
        self.generate_calls: list[dict] = []
        self.embed_calls: list[list[str]] = []

    async def generate(self, prompt, *, system=None, format=None, call_site=None):
        self.generate_calls.append({"prompt": prompt, "system": system, "format": format, "call_site": call_site})
        if system == QUERY_REWRITE_SYSTEM_PROMPT:
            return self._rewritten
        if system == FACT_UPDATE_SYSTEM_PROMPT:
            return self.fact_update
        return self._answer

    async def embed(self, texts, *, call_site=None):
        self.embed_calls.append(list(texts))
        return [self._query_embedding for _ in texts]


async def make_document_with_chunk(db_session) -> Document:
    document = Document(path="/docs/storefront.md", doc_type="markdown", content_hash="abc123")
    db_session.add(document)
    await db_session.flush()
    db_session.add(
        Chunk(
            document_id=document.id,
            chunk_index=0,
            content="SKU stands for Stock Keeping Unit.",
            section="Terminology",
            embedding=make_vector((0, 1.0)),
        )
    )
    await db_session.flush()
    return document


async def test_answer_question_grounds_answer_in_retrieved_chunks(db_session):
    await make_document_with_chunk(db_session)

    provider = FakeProvider(query_embedding=make_vector((0, 1.0)), answer="A SKU is a Stock Keeping Unit [1].")

    result = await answer_question(db_session, provider, "What is a SKU?")

    assert result.answer == "A SKU is a Stock Keeping Unit [1]."
    assert result.sources == [
        RetrievedChunk(document_path="/docs/storefront.md", section="Terminology", content="SKU stands for Stock Keeping Unit.")
    ]

    # No prior history, so no query-rewrite call: one fact-detection call, one answer call,
    # and one title-generation call (first turn, conversation has no title yet).
    assert len(provider.generate_calls) == 3
    assert provider.generate_calls[0]["system"] == FACT_UPDATE_SYSTEM_PROMPT
    answer_call = next(c for c in provider.generate_calls if c["system"] == CHAT_SYSTEM_PROMPT)
    assert "SKU stands for Stock Keeping Unit." in answer_call["prompt"]
    assert "What is a SKU?" in answer_call["prompt"]

    messages = (
        await db_session.execute(
            select(Message).where(Message.conversation_id == result.conversation_id).order_by(Message.created_at)
        )
    ).scalars().all()
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "What is a SKU?"
    assert messages[1].content == "A SKU is a Stock Keeping Unit [1]."
    assert messages[1].sources == [
        {"document_path": "/docs/storefront.md", "section": "Terminology", "project_name": None}
    ]


async def test_answer_question_rewrites_query_for_followups(db_session):
    await make_document_with_chunk(db_session)

    conversation = Conversation()
    db_session.add(conversation)
    await db_session.flush()
    db_session.add(Message(conversation_id=conversation.id, role="user", content="What is in the storefront project?"))
    db_session.add(Message(conversation_id=conversation.id, role="assistant", content="It covers the storefront."))
    await db_session.flush()

    provider = FakeProvider(
        query_embedding=make_vector((0, 1.0)),
        answer="A SKU is a Stock Keeping Unit [1].",
        rewritten="What does SKU mean in the storefront project?",
    )

    result = await answer_question(db_session, provider, "What does SKU mean?", conversation)

    # Query rewrite (history present), fact detection, the answer call, and the title call
    # (conversation has no title yet).
    assert len(provider.generate_calls) == 4
    assert provider.generate_calls[0]["system"] == QUERY_REWRITE_SYSTEM_PROMPT
    assert provider.embed_calls == [["What does SKU mean in the storefront project?"]]
    assert result.conversation_id == conversation.id

    messages = (
        await db_session.execute(
            select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
        )
    ).scalars().all()
    assert len(messages) == 4


def test_truncate_history_keeps_most_recent_whole_messages():
    messages = [
        Message(role="user", content="a" * 3000),
        Message(role="assistant", content="b" * 3000),
        Message(role="user", content="c" * 100),
    ]

    history = _truncate_history(messages, max_chars=3500)

    assert [turn.content[0] for turn in history] == ["b", "c"]


def test_truncate_history_keeps_at_least_the_latest_message():
    messages = [Message(role="user", content="x" * 10000)]

    history = _truncate_history(messages, max_chars=100)

    assert len(history) == 1


def test_build_query_rewrite_prompt_includes_history_and_message():
    history = [
        HistoryTurn(role="user", content="What is in the storefront project?"),
        HistoryTurn(role="assistant", content="It covers the storefront."),
    ]

    prompt = build_query_rewrite_prompt(history, "What does SKU mean?")

    assert "User: What is in the storefront project?" in prompt
    assert "Assistant: It covers the storefront." in prompt
    assert prompt.endswith("Latest message: What does SKU mean?")


def test_build_fact_update_prompt_includes_history_and_message():
    history = [
        HistoryTurn(role="user", content="What is in the storefront project?"),
        HistoryTurn(role="assistant", content="It covers the storefront."),
    ]

    prompt = build_fact_update_prompt(history, "The SLA changed to 80%.")

    assert "User: What is in the storefront project?" in prompt
    assert "Assistant: It covers the storefront." in prompt
    assert prompt.endswith("Latest message: The SLA changed to 80%.")


def test_build_chat_prompt_numbers_and_labels_sources():
    context = [
        RetrievedChunk(document_path="/docs/a.md", section="Intro", content="Hello"),
        RetrievedChunk(document_path="/docs/b.md", section=None, content="World"),
    ]

    prompt = build_chat_prompt("What is this about?", context, [])

    assert "[1] (/docs/a.md, section: Intro)\nHello" in prompt
    assert "[2] (/docs/b.md)\nWorld" in prompt
    assert prompt.endswith("Question: What is this about?")


def test_build_chat_prompt_includes_history():
    history = [
        HistoryTurn(role="user", content="What is in the storefront project?"),
        HistoryTurn(role="assistant", content="It covers the storefront."),
    ]

    prompt = build_chat_prompt("Who manages it?", [], history)

    assert "Conversation so far:" in prompt
    assert "User: What is in the storefront project?" in prompt
    assert "Assistant: It covers the storefront." in prompt
    assert prompt.endswith("Question: Who manages it?")


def test_build_chat_prompt_includes_known_facts_immediately_before_question():
    history = [
        HistoryTurn(role="user", content="What is in the storefront project?"),
        HistoryTurn(role="assistant", content="It covers the storefront."),
    ]
    context = [RetrievedChunk(document_path="/docs/a.md", section="Intro", content="Hello")]
    known_facts = "Known facts:\nStorefront Redesign SLA value: 80%"

    prompt = build_chat_prompt("Who manages it?", context, history, known_facts=known_facts)

    # The known facts block comes after the conversation history and numbered context, and
    # immediately precedes the question, closest to where the model starts generating.
    assert prompt.index("Conversation so far:") < prompt.index("[1] (/docs/a.md, section: Intro)")
    assert prompt.index("[1] (/docs/a.md, section: Intro)") < prompt.index(known_facts)
    assert known_facts + "\n\nQuestion: Who manages it?" in prompt


async def test_answer_question_records_a_fact_from_chat(db_session):
    """A message stating a new fact results in a Fact row being recorded."""
    await make_document_with_chunk(db_session)

    fact_update = (
        '{"should_record": true, "project": "", "subject": "Storefront Redesign SLA", '
        '"predicate": "value", "object": "", "value": "80%"}'
    )
    provider = FakeProvider(
        query_embedding=make_vector((0, 1.0)),
        answer="Got it, I will remember that.",
        fact_update=fact_update,
    )

    await answer_question(db_session, provider, "The SLA changed to 80%")

    facts = (await db_session.execute(select(Fact))).scalars().all()
    assert len(facts) == 1
    assert facts[0].predicate == "value"
    assert facts[0].value == "80%"
    assert facts[0].source_type == "message"
    assert facts[0].status == "pending"


async def test_answer_question_appends_new_fact_rather_than_replacing(db_session):
    """Recording the same (subject, predicate) twice keeps both values as separate rows."""
    await make_document_with_chunk(db_session)

    first_update = (
        '{"should_record": true, "project": "", "subject": "Storefront Redesign SLA", '
        '"predicate": "value", "object": "", "value": "80%"}'
    )
    second_update = (
        '{"should_record": true, "project": "", "subject": "Storefront Redesign SLA", '
        '"predicate": "value", "object": "", "value": "90%"}'
    )

    provider_one = FakeProvider(
        query_embedding=make_vector((0, 1.0)),
        answer="Noted, SLA is now 80%.",
        fact_update=first_update,
    )
    await answer_question(db_session, provider_one, "The SLA changed to 80%")

    provider_two = FakeProvider(
        query_embedding=make_vector((0, 1.0)),
        answer="Noted, SLA is now 90%.",
        fact_update=second_update,
    )
    await answer_question(db_session, provider_two, "The SLA changed to 90%")

    facts = (
        await db_session.execute(select(Fact).where(Fact.predicate == "value").order_by(Fact.created_at))
    ).scalars().all()

    assert len(facts) == 2
    # All facts about this subject/predicate share the same subject reference.
    assert facts[0].subject_type == facts[1].subject_type
    assert facts[0].subject_id == facts[1].subject_id
    assert {f.value for f in facts} == {"80%", "90%"}


async def test_answer_question_surfaces_known_facts_for_history_questions(db_session):
    """A later question about the subject sees both previously recorded values in the prompt."""
    await make_document_with_chunk(db_session)

    first_update = (
        '{"should_record": true, "project": "", "subject": "Storefront Redesign SLA", '
        '"predicate": "value", "object": "", "value": "80%"}'
    )
    second_update = (
        '{"should_record": true, "project": "", "subject": "Storefront Redesign SLA", '
        '"predicate": "value", "object": "", "value": "90%"}'
    )

    provider_one = FakeProvider(
        query_embedding=make_vector((0, 1.0)),
        answer="Noted, SLA is now 80%.",
        fact_update=first_update,
    )
    await answer_question(db_session, provider_one, "The SLA changed to 80%")

    provider_two = FakeProvider(
        query_embedding=make_vector((0, 1.0)),
        answer="Noted, SLA is now 90%.",
        fact_update=second_update,
    )
    await answer_question(db_session, provider_two, "The SLA changed to 90%")

    # "Known facts" only reflect confirmed facts; confirm both recorded above.
    pending_facts = (await db_session.execute(select(Fact).where(Fact.predicate == "value"))).scalars().all()
    for fact in pending_facts:
        fact.status = "confirmed"
    await db_session.commit()

    provider_three = FakeProvider(
        query_embedding=make_vector((0, 1.0)),
        answer="The SLA went from 80% to 90%.",
        fact_update='{"should_record": false}',
    )
    await answer_question(db_session, provider_three, "How did the Storefront Redesign SLA change?")

    answer_calls = [call for call in provider_three.generate_calls if call["system"] == CHAT_SYSTEM_PROMPT]
    assert len(answer_calls) == 1
    prompt = answer_calls[0]["prompt"]

    assert "Known facts" in prompt
    assert "80%" in prompt
    assert "90%" in prompt


async def test_answer_question_does_not_record_a_fact_for_a_plain_question(db_session):
    """A plain question with no asserted fact results in no Fact rows."""
    await make_document_with_chunk(db_session)

    provider = FakeProvider(
        query_embedding=make_vector((0, 1.0)),
        answer="This project is about the storefront.",
        fact_update='{"should_record": false}',
    )

    await answer_question(db_session, provider, "What is this project about?")

    facts = (await db_session.execute(select(Fact))).scalars().all()
    assert facts == []
