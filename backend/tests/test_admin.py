import asyncio
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.db.models import (
    Chunk,
    Conversation,
    ConversationAttachment,
    Document,
    Fact,
    Message,
    Person,
    Project,
    ProjectResolution,
    Relation,
    Team,
    Term,
    Topic,
)
from app.db.session import engine, get_db
from app.main import app
from tests.test_chat import make_vector


async def seed_one_row_per_table(db_session) -> None:
    """Seed at least one row in every application table, including several that are easy
    to leave out of a hand-rolled TRUNCATE list (Term, Team, Person, Topic, Relation,
    ProjectResolution, ConversationAttachment)."""
    project = Project(name="Storefront Redesign", description="Revamp the storefront")
    db_session.add(project)
    await db_session.flush()

    document = Document(
        project_id=project.id,
        path="/tmp/admin-reset-test.md",
        doc_type="markdown",
        content_hash="abc123",
        origin="ingested",
    )
    db_session.add(document)
    await db_session.flush()

    db_session.add(
        Chunk(
            document_id=document.id,
            chunk_index=0,
            content="The storefront redesign covers the checkout flow.",
            section="Overview",
            embedding=make_vector(),
        )
    )

    db_session.add(
        Term(
            project_id=project.id,
            document_id=document.id,
            source_section="Terminology",
            term="SKU",
            definition="Stock keeping unit",
        )
    )

    team = Team(
        project_id=project.id,
        document_id=document.id,
        source_section="Team",
        name="Core Team",
    )
    db_session.add(team)
    await db_session.flush()

    db_session.add(
        Person(
            project_id=project.id,
            team_id=team.id,
            document_id=document.id,
            source_section="Team",
            name="Alex",
            role="Engineer",
        )
    )

    topic = Topic(
        project_id=project.id,
        document_id=document.id,
        source_section="Overview",
        name="Checkout flow",
        description="Discussion of the checkout flow",
    )
    db_session.add(topic)
    await db_session.flush()

    db_session.add(
        ProjectResolution(
            document_id=document.id,
            candidate_name="Storefront Redesign",
            candidate_description="Revamp the storefront",
            candidate_project_ids=[project.id],
            status="pending",
        )
    )

    db_session.add(
        Relation(
            subject_type="person",
            subject_id=uuid.uuid4(),
            relation_label="member_of",
            object_type="team",
            object_id=team.id,
            document_id=document.id,
            source_section="Team",
        )
    )

    conversation = Conversation()
    db_session.add(conversation)
    await db_session.flush()

    message = Message(
        conversation_id=conversation.id,
        role="user",
        content="What is the SLA for checkout?",
    )
    db_session.add(message)
    await db_session.flush()

    db_session.add(ConversationAttachment(conversation_id=conversation.id, document_id=document.id))

    db_session.add(
        Fact(
            subject_type="topic",
            subject_id=topic.id,
            predicate="value",
            value="80%",
            source_type="message",
            source_id=message.id,
            status="pending",
        )
    )

    await db_session.flush()


async def count_rows(db_session, table_name: str) -> int:
    result = await db_session.execute(text(f'SELECT count(*) FROM "{table_name}"'))
    return result.scalar_one()


async def test_admin_reset_wipes_every_application_table(db_session):
    """POST /admin/reset should truncate every application table, not just the ones a
    hand-written TRUNCATE list happens to remember. Seed one row in each SQLAlchemy model's
    table, call the endpoint, and then assert every table known to the ORM metadata (not
    just the seeded ones) is empty afterwards -- this fails loudly if a future table is
    left off the reset."""
    await seed_one_row_per_table(db_session)
    await db_session.commit()

    table_names = sorted(table.name for table in Base.metadata.sorted_tables)
    assert table_names, "expected the ORM metadata to know about at least one table"

    pre_reset_counts = {name: await count_rows(db_session, name) for name in table_names}
    assert any(count > 0 for count in pre_reset_counts.values()), "seeding did not create any rows"
    seeded_tables = {
        "projects",
        "documents",
        "chunks",
        "terms",
        "teams",
        "people",
        "topics",
        "project_resolutions",
        "conversations",
        "messages",
        "conversation_attachments",
        "relations",
        "facts",
    }
    for name in seeded_tables:
        assert pre_reset_counts[name] > 0, f"expected {name} to have a seeded row before reset"

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/admin/reset")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code in (200, 204), response.text

    for name in table_names:
        assert await count_rows(db_session, name) == 0, f"expected {name} to be empty after /admin/reset"


async def test_admin_reset_returns_409_when_another_transaction_holds_a_conflicting_lock(db_session):
    """If another session has an in-flight, uncommitted write touching one of the tables
    /admin/reset wants to wipe, the endpoint must not block until that transaction commits
    and then silently truncate the data it just wrote. It should fail fast instead, so the
    caller can retry, returning 409 Conflict rather than hanging or succeeding.

    The blocking transaction lives on a second, independent engine connection (not the
    `db_session` fixture's connection, and not the connection the app's overridden `get_db`
    uses to run the reset) so the two are genuinely concurrent Postgres transactions rather
    than the same session seeing its own lock.
    """

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    blocking_connection = await engine.connect()
    await blocking_connection.begin()
    blocking_session_factory = async_sessionmaker(
        bind=blocking_connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    blocking_session = blocking_session_factory()
    try:
        blocking_session.add(
            Project(name="In-Flight Project", description="Uncommitted write holding a table lock")
        )
        # flush (not commit): this leaves the transaction open, holding Postgres's implicit
        # row-exclusive lock on `projects` for as long as the transaction stays uncommitted.
        await blocking_session.flush()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            try:
                response = await asyncio.wait_for(client.post("/admin/reset"), timeout=10)
            except asyncio.TimeoutError:
                raise AssertionError(
                    "POST /admin/reset blocked instead of failing fast: it waited on the lock "
                    "held by the other transaction rather than using NOWAIT and returning 409"
                ) from None

        assert response.status_code == 409, (
            f"expected 409 Conflict while another transaction holds a conflicting lock, "
            f"got {response.status_code}: {response.text}"
        )
    finally:
        await blocking_session.rollback()
        await blocking_session.close()
        await blocking_connection.close()
        app.dependency_overrides.pop(get_db, None)


async def test_admin_reset_is_idempotent_on_an_already_empty_database(db_session):
    """Calling reset with nothing to wipe should still succeed, not error on empty tables."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/admin/reset")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code in (200, 204), response.text


async def test_admin_reset_clears_the_storage_directory(db_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Reset truncates every Document row, so any durable stored file copy left on disk
    afterward is orphaned garbage. /admin/reset should remove the whole storage_dir tree,
    not just the database rows that used to point at it."""
    storage_root = tmp_path / "storage-root"
    monkeypatch.setattr(settings, "storage_dir", str(storage_root))

    orphan = storage_root / "some-document-id" / "notes.md"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("leftover content")
    assert orphan.exists()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/admin/reset")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code in (200, 204), response.text
    assert not storage_root.exists(), "expected /admin/reset to remove the storage directory tree"
