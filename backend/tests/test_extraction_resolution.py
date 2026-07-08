import uuid

from sqlalchemy import select

from app.db.models import Document, Person, Project, ProjectResolution, Team, Term, Topic
from sqlalchemy import func

from app.extraction.resolution import apply_resolution, resolve_entity_ref, resolve_project
from app.extraction.schemas import ExtractedProject, ProjectResolutionResult


async def make_document(db_session) -> Document:
    document = Document(path="/docs/storefront.md", doc_type="markdown", content_hash="abc123")
    db_session.add(document)
    await db_session.flush()
    return document


class FakeProvider:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def generate(self, prompt, *, system=None, format=None, call_site=None):
        self.calls.append({"prompt": prompt, "system": system, "format": format, "call_site": call_site})
        return self._responses.pop(0)

    async def embed(self, texts, *, call_site=None):
        return [[0.0, 0.0] for _ in texts]


async def test_resolve_project_returns_new_when_no_existing_projects(db_session):
    provider = FakeProvider(responses=[])
    candidate = ExtractedProject(name="Storefront", description="Online shop")

    project_id, outcome = await resolve_project(db_session, provider, uuid.uuid4(), candidate)

    assert outcome == "new"
    project = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    assert project.name == "Storefront"
    assert provider.calls == []


async def test_resolve_project_match(db_session):
    existing = Project(name="Storefront API", description="Backend service")
    db_session.add(existing)
    await db_session.flush()

    response = ProjectResolutionResult(outcome="match", project_id=str(existing.id)).model_dump_json()
    provider = FakeProvider(responses=[response])
    candidate = ExtractedProject(name="Storefront", description="Backend service for the storefront")

    project_id, outcome = await resolve_project(db_session, provider, uuid.uuid4(), candidate)

    assert outcome == "match"
    assert project_id == existing.id


async def test_resolve_project_match_with_unrecognized_id_degrades_to_ambiguous(db_session):
    existing = Project(name="Storefront API", description="Backend service")
    db_session.add(existing)
    await db_session.flush()

    response = ProjectResolutionResult(outcome="match", project_id=str(uuid.uuid4())).model_dump_json()
    provider = FakeProvider(responses=[response])
    candidate = ExtractedProject(name="Storefront", description="Backend service for the storefront")
    document = await make_document(db_session)

    project_id, outcome = await resolve_project(db_session, provider, document.id, candidate)

    assert outcome == "ambiguous"
    assert project_id is None

    resolution = (
        await db_session.execute(select(ProjectResolution).where(ProjectResolution.document_id == document.id))
    ).scalar_one()
    assert resolution.candidate_project_ids == [existing.id]


async def test_resolve_project_stays_with_documents_existing_project_id(db_session):
    existing = Project(name="Storefront API", description="Backend service")
    other = Project(name="Checkout", description="Unrelated")
    db_session.add_all([existing, other])
    await db_session.flush()

    provider = FakeProvider(responses=[])
    candidate = ExtractedProject(name="Storefront", description="Backend service for the storefront")

    project_id, outcome = await resolve_project(
        db_session, provider, uuid.uuid4(), candidate, existing_project_id=existing.id
    )

    assert (project_id, outcome) == (existing.id, "match")
    assert provider.calls == []


async def test_resolve_project_ignores_existing_project_id_if_project_no_longer_exists(db_session):
    other = Project(name="Checkout", description="Unrelated")
    db_session.add(other)
    await db_session.flush()
    deleted_project_id = uuid.uuid4()

    response = ProjectResolutionResult(outcome="new").model_dump_json()
    provider = FakeProvider(responses=[response])
    candidate = ExtractedProject(name="Storefront", description="Online shop")

    project_id, outcome = await resolve_project(
        db_session, provider, uuid.uuid4(), candidate, existing_project_id=deleted_project_id
    )

    assert outcome == "new"
    assert provider.calls != []


async def test_resolve_project_new_with_existing_projects(db_session):
    db_session.add(Project(name="Other Project", description="Unrelated"))
    await db_session.flush()

    response = ProjectResolutionResult(outcome="new").model_dump_json()
    provider = FakeProvider(responses=[response])
    candidate = ExtractedProject(name="Storefront", description="Online shop")

    project_id, outcome = await resolve_project(db_session, provider, uuid.uuid4(), candidate)

    assert outcome == "new"
    project = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    assert project.name == "Storefront"


async def test_resolve_project_ambiguous_creates_project_resolution(db_session):
    first = Project(name="Storefront EU", description="European storefront")
    second = Project(name="Storefront US", description="US storefront")
    db_session.add_all([first, second])
    await db_session.flush()

    response = ProjectResolutionResult(
        outcome="ambiguous", candidate_ids=[str(first.id), str(second.id)]
    ).model_dump_json()
    provider = FakeProvider(responses=[response])
    candidate = ExtractedProject(name="Storefront", description="The storefront")
    document = await make_document(db_session)

    project_id, outcome = await resolve_project(db_session, provider, document.id, candidate)

    assert outcome == "ambiguous"
    assert project_id is None

    resolution = (
        await db_session.execute(select(ProjectResolution).where(ProjectResolution.document_id == document.id))
    ).scalar_one()
    assert resolution.candidate_name == "Storefront"
    assert resolution.status == "pending"
    assert set(resolution.candidate_project_ids) == {first.id, second.id}


async def test_resolve_entity_ref_picks_one_deterministically_when_name_is_duplicated(db_session):
    project = Project(name="Storefront")
    db_session.add(project)
    await db_session.flush()
    document = await make_document(db_session)
    first = Person(project_id=project.id, document_id=document.id, name="Bob", role="Engineer")
    db_session.add(first)
    await db_session.flush()
    second = Person(project_id=project.id, document_id=document.id, name="Bob", role="Designer")
    db_session.add(second)
    await db_session.flush()

    entity_type, entity_id = await resolve_entity_ref(db_session, project.id, "Bob", {}, document.id)
    assert entity_type == "person"
    assert entity_id in {first.id, second.id}

    again_type, again_id = await resolve_entity_ref(db_session, project.id, "Bob", {}, document.id)
    assert (again_type, again_id) == (entity_type, entity_id)


async def test_resolve_entity_ref_uses_local_entities(db_session):
    local_id = uuid.uuid4()
    local_entities = {"Alice": ("person", local_id)}

    entity_type, entity_id = await resolve_entity_ref(db_session, None, "Alice", local_entities, uuid.uuid4())

    assert (entity_type, entity_id) == ("person", local_id)


async def test_resolve_entity_ref_finds_existing_person(db_session):
    project = Project(name="Storefront")
    db_session.add(project)
    await db_session.flush()
    document = await make_document(db_session)
    person = Person(project_id=project.id, document_id=document.id, name="Bob", role="Engineer")
    db_session.add(person)
    await db_session.flush()

    entity_type, entity_id = await resolve_entity_ref(db_session, project.id, "Bob", {}, document.id)

    assert (entity_type, entity_id) == ("person", person.id)


async def test_resolve_entity_ref_finds_existing_project_by_name(db_session):
    other_project = Project(name="Checkout")
    db_session.add(other_project)
    await db_session.flush()

    entity_type, entity_id = await resolve_entity_ref(db_session, None, "Checkout", {}, uuid.uuid4())

    assert (entity_type, entity_id) == ("project", other_project.id)


async def test_resolve_entity_ref_creates_and_reuses_topic(db_session):
    project = Project(name="Storefront")
    db_session.add(project)
    await db_session.flush()
    document = await make_document(db_session)

    entity_type, topic_id = await resolve_entity_ref(db_session, project.id, "Checkout Flow", {}, document.id)
    assert entity_type == "topic"

    topics = (
        (await db_session.execute(select(Topic).where(Topic.name == "Checkout Flow"))).scalars().all()
    )
    assert [t.id for t in topics] == [topic_id]

    entity_type_again, topic_id_again = await resolve_entity_ref(
        db_session, project.id, "Checkout Flow", {}, document.id
    )
    assert (entity_type_again, topic_id_again) == ("topic", topic_id)


async def test_resolve_entity_ref_with_no_document_creates_topic_without_document(db_session):
    """Chat-derived facts resolve entities with no source document (document_id=None)."""
    entity_type, topic_id = await resolve_entity_ref(
        db_session, project_id=None, name="checkout redesign flow", local_entities={}, document_id=None
    )

    assert entity_type == "topic"

    topic = (await db_session.execute(select(Topic).where(Topic.id == topic_id))).scalar_one()
    assert topic.document_id is None
    assert topic.name == "checkout redesign flow"


async def make_pending_resolution(db_session) -> tuple[Document, ProjectResolution]:
    document = await make_document(db_session)
    resolution = ProjectResolution(
        document_id=document.id,
        candidate_name="Storefront",
        candidate_description="The storefront",
        candidate_project_ids=[],
    )
    db_session.add(resolution)
    db_session.add(Term(project_id=None, document_id=document.id, term="SKU", definition="Stock Keeping Unit"))
    db_session.add(Team(project_id=None, document_id=document.id, name="Core Team"))
    db_session.add(Person(project_id=None, document_id=document.id, name="Alice", role="Lead"))
    db_session.add(Topic(project_id=None, document_id=document.id, name="Checkout Flow"))
    await db_session.flush()
    return document, resolution


async def test_apply_resolution_creates_new_project_and_backfills_entities(db_session):
    document, resolution = await make_pending_resolution(db_session)

    project_id = await apply_resolution(db_session, resolution, None)

    await db_session.refresh(document)
    assert document.project_id == project_id
    assert resolution.status == "resolved"
    assert resolution.resolved_project_id == project_id

    project = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    assert project.name == "Storefront"
    assert project.description == "The storefront"

    for model in (Term, Team, Person, Topic):
        rows = (await db_session.execute(select(model).where(model.document_id == document.id))).scalars().all()
        assert all(row.project_id == project_id for row in rows)


async def test_apply_resolution_attaches_to_existing_project(db_session):
    document, resolution = await make_pending_resolution(db_session)
    existing = Project(name="Storefront API", description="Backend service")
    db_session.add(existing)
    await db_session.flush()

    project_id = await apply_resolution(db_session, resolution, existing.id)

    assert project_id == existing.id
    await db_session.refresh(document)
    assert document.project_id == existing.id

    person = (await db_session.execute(select(Person).where(Person.document_id == document.id))).scalar_one()
    assert person.project_id == existing.id


async def test_apply_resolution_reuses_existing_project_with_same_name(db_session):
    document1, resolution1 = await make_pending_resolution(db_session)

    doc2 = Document(path="/docs/storefront2.md", doc_type="markdown", content_hash="def456")
    db_session.add(doc2)
    await db_session.flush()
    resolution2 = ProjectResolution(
        document_id=doc2.id,
        candidate_name="Storefront",
        candidate_description="The storefront",
        candidate_project_ids=[],
    )
    db_session.add(resolution2)
    await db_session.flush()

    project_id1 = await apply_resolution(db_session, resolution1, None)
    project_id2 = await apply_resolution(db_session, resolution2, None)

    assert project_id1 == project_id2

    projects = (await db_session.execute(select(Project).where(Project.name == "Storefront"))).scalars().all()
    assert len(projects) == 1

    await db_session.refresh(document1)
    await db_session.refresh(doc2)
    assert document1.project_id == project_id1
    assert doc2.project_id == project_id1


async def test_apply_resolution_reuses_existing_project_case_insensitive(db_session):
    existing = Project(name="storefront", description="Lowercase name")
    db_session.add(existing)
    await db_session.flush()

    document = await make_document(db_session)
    resolution = ProjectResolution(
        document_id=document.id,
        candidate_name="STOREFRONT",
        candidate_description="Uppercase candidate",
        candidate_project_ids=[],
    )
    db_session.add(resolution)
    await db_session.flush()

    project_id = await apply_resolution(db_session, resolution, None)

    assert project_id == existing.id
    projects = (
        await db_session.execute(select(Project).where(func.lower(Project.name) == "storefront"))
    ).scalars().all()
    assert len(projects) == 1
