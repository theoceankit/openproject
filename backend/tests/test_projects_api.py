from httpx import ASGITransport, AsyncClient

from app.db.models import Project
from app.db.session import get_db
from app.main import app


async def test_list_projects_orders_by_name(db_session):
    db_session.add_all([Project(name="Storefront"), Project(name="Checkout")])
    await db_session.flush()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/projects")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [p["name"] for p in body["items"]] == ["Checkout", "Storefront"]


async def test_list_projects_paginates_with_limit_and_offset(db_session):
    db_session.add_all([Project(name=f"Project {i}") for i in range(5)])
    await db_session.flush()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first_page = await client.get("/projects", params={"limit": 2, "offset": 0})
            second_page = await client.get("/projects", params={"limit": 2, "offset": 2})
    finally:
        app.dependency_overrides.pop(get_db, None)

    first_body = first_page.json()
    second_body = second_page.json()
    assert first_body["total"] == 5
    assert second_body["total"] == 5
    assert [p["name"] for p in first_body["items"]] == ["Project 0", "Project 1"]
    assert [p["name"] for p in second_body["items"]] == ["Project 2", "Project 3"]
