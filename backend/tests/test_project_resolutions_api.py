from httpx import ASGITransport, AsyncClient

from sqlalchemy import select

from app.db.models import Document, Project, ProjectResolution
from app.db.session import get_db
from app.main import app


async def make_pending_resolution(db_session) -> tuple[Document, ProjectResolution]:
    document = Document(path="/docs/storefront.md", doc_type="markdown", content_hash="abc123")
    db_session.add(document)
    await db_session.flush()
    resolution = ProjectResolution(
        document_id=document.id,
        candidate_name="Storefront",
        candidate_description="The storefront",
        candidate_project_ids=[],
    )
    db_session.add(resolution)
    await db_session.flush()
    return document, resolution


async def test_list_and_resolve_to_new_project(db_session):
    document, resolution = await make_pending_resolution(db_session)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            list_response = await client.get("/project-resolutions")
            assert list_response.status_code == 200
            list_body = list_response.json()
            assert list_body["total"] == 1
            [item] = list_body["items"]
            assert item["candidate_name"] == "Storefront"
            assert item["document_path"] == "/docs/storefront.md"
            assert item["status"] == "pending"

            resolve_response = await client.post(f"/project-resolutions/{item['id']}/resolve", json={})
            assert resolve_response.status_code == 200
            body = resolve_response.json()
            assert body["status"] == "resolved"

            second_response = await client.get("/project-resolutions")
            assert second_response.json() == {"items": [], "total": 0}
    finally:
        app.dependency_overrides.pop(get_db, None)

    await db_session.refresh(document)
    assert str(document.project_id) == body["project_id"]
    await db_session.refresh(resolution)
    assert resolution.status == "resolved"


async def test_list_project_resolutions_paginates_with_limit_and_offset(db_session):
    for i in range(3):
        document = Document(path=f"/docs/doc{i}.md", doc_type="markdown", content_hash=f"hash{i}")
        db_session.add(document)
        await db_session.flush()
        db_session.add(
            ProjectResolution(
                document_id=document.id,
                candidate_name=f"Candidate {i}",
                candidate_description="",
                candidate_project_ids=[],
            )
        )
        await db_session.flush()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            page = await client.get("/project-resolutions", params={"limit": 2, "offset": 1})
    finally:
        app.dependency_overrides.pop(get_db, None)

    body = page.json()
    assert body["total"] == 3
    assert [item["candidate_name"] for item in body["items"]] == ["Candidate 1", "Candidate 2"]


async def test_resolve_to_existing_project(db_session):
    document, resolution = await make_pending_resolution(db_session)
    existing = Project(name="Storefront API", description="Backend service")
    db_session.add(existing)
    await db_session.flush()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resolve_response = await client.post(
                f"/project-resolutions/{resolution.id}/resolve", json={"project_id": str(existing.id)}
            )
            assert resolve_response.status_code == 200
            assert resolve_response.json()["project_id"] == str(existing.id)
    finally:
        app.dependency_overrides.pop(get_db, None)

    await db_session.refresh(document)
    assert document.project_id == existing.id


async def test_resolve_two_to_new_project_reuses_same_project(db_session):
    document1 = Document(path="/docs/storefront.md", doc_type="markdown", content_hash="abc123")
    document2 = Document(path="/docs/storefront2.md", doc_type="markdown", content_hash="def456")
    db_session.add_all([document1, document2])
    await db_session.flush()

    resolution1 = ProjectResolution(
        document_id=document1.id,
        candidate_name="Storefront",
        candidate_description="The storefront",
        candidate_project_ids=[],
    )
    resolution2 = ProjectResolution(
        document_id=document2.id,
        candidate_name="Storefront",
        candidate_description="The storefront",
        candidate_project_ids=[],
    )
    db_session.add_all([resolution1, resolution2])
    await db_session.flush()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.post(f"/project-resolutions/{resolution1.id}/resolve", json={})
            assert r1.status_code == 200
            project_id_1 = r1.json()["project_id"]

            r2 = await client.post(f"/project-resolutions/{resolution2.id}/resolve", json={})
            assert r2.status_code == 200
            project_id_2 = r2.json()["project_id"]
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert project_id_1 == project_id_2

    projects = (
        await db_session.execute(select(Project).where(Project.name == "Storefront"))
    ).scalars().all()
    assert len(projects) == 1


async def test_resolve_unknown_resolution_returns_404(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/project-resolutions/00000000-0000-0000-0000-000000000000/resolve", json={}
            )
            assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
