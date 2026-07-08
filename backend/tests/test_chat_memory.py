from sqlalchemy import select

from app.chat.memory import build_known_facts_block, describe_fact, record_fact, resolve_fact
from app.db.models import Conversation, Fact, Message, Project, Topic
from app.extraction.schemas import FactUpdateResult


async def make_message(db_session) -> Message:
    conversation = Conversation()
    db_session.add(conversation)
    await db_session.flush()
    message = Message(conversation_id=conversation.id, role="user", content="The SLA changed to 80%")
    db_session.add(message)
    await db_session.flush()
    return message


def make_update(value: str = "80%") -> FactUpdateResult:
    return FactUpdateResult(
        should_record=True,
        project="",
        subject="Storefront Redesign SLA",
        predicate="value",
        object="",
        value=value,
    )


async def test_record_fact_is_pending(db_session):
    message = await make_message(db_session)

    fact = await record_fact(db_session, make_update(), source_message_id=message.id)

    assert fact is not None
    assert fact.status == "pending"


async def test_describe_fact_returns_display_names(db_session):
    message = await make_message(db_session)

    fact = await record_fact(db_session, make_update(), source_message_id=message.id)
    description = await describe_fact(db_session, fact)

    assert description == {
        "id": str(fact.id),
        "subject": "Storefront Redesign SLA",
        "predicate": "value",
        "object": "80%",
    }


async def test_known_facts_block_excludes_pending_and_rejected(db_session):
    message = await make_message(db_session)
    fact = await record_fact(db_session, make_update(), source_message_id=message.id)
    await db_session.commit()

    assert await build_known_facts_block(db_session, "Storefront Redesign SLA value") is None

    await resolve_fact(db_session, fact, confirm=False)
    await db_session.commit()

    assert await build_known_facts_block(db_session, "Storefront Redesign SLA value") is None


async def test_known_facts_block_includes_confirmed_fact(db_session):
    message = await make_message(db_session)
    fact = await record_fact(db_session, make_update(), source_message_id=message.id)
    await resolve_fact(db_session, fact, confirm=True)
    await db_session.commit()

    block = await build_known_facts_block(db_session, "Storefront Redesign SLA value")

    assert block is not None
    assert "80%" in block


async def test_record_fact_reuses_project_scoped_topic_for_object(db_session):
    """A duplicate update with no project still resolves the object within the subject's project."""
    message = await make_message(db_session)
    project = Project(name="Storefront Redesign", description="")
    db_session.add(project)
    await db_session.flush()

    first_update = FactUpdateResult(
        should_record=True,
        project="Storefront Redesign",
        subject="Storefront Redesign",
        predicate="owner",
        object="Alice",
        value="",
    )
    first_fact = await record_fact(db_session, first_update, source_message_id=message.id)
    assert first_fact is not None
    await resolve_fact(db_session, first_fact, confirm=True)
    await db_session.commit()

    second_update = FactUpdateResult(
        should_record=True,
        project="",
        subject="Storefront Redesign",
        predicate="owner",
        object="Alice",
        value="",
    )
    second_fact = await record_fact(db_session, second_update, source_message_id=message.id)

    assert second_fact is None
    topics = (await db_session.execute(select(Topic).where(Topic.name == "Alice"))).scalars().all()
    assert len(topics) == 1


async def test_record_fact_skips_exact_duplicate(db_session):
    """Recording the same fact again, once confirmed, does not insert another row."""
    message = await make_message(db_session)

    first_fact = await record_fact(db_session, make_update(), source_message_id=message.id)
    assert first_fact is not None
    await resolve_fact(db_session, first_fact, confirm=True)
    await db_session.commit()

    second_fact = await record_fact(db_session, make_update(), source_message_id=message.id)

    assert second_fact is None
    facts = (await db_session.execute(select(Fact).where(Fact.source_id == message.id))).scalars().all()
    assert len(facts) == 1


async def test_record_fact_records_changed_value(db_session):
    """A different value for the same subject/predicate is still recorded as a new row."""
    message = await make_message(db_session)

    first_fact = await record_fact(db_session, make_update(value="80%"), source_message_id=message.id)
    assert first_fact is not None
    await resolve_fact(db_session, first_fact, confirm=True)
    await db_session.commit()

    second_fact = await record_fact(db_session, make_update(value="90%"), source_message_id=message.id)

    assert second_fact is not None
    facts = (await db_session.execute(select(Fact).where(Fact.predicate == "value"))).scalars().all()
    assert len(facts) == 2
    assert {f.value for f in facts} == {"80%", "90%"}
