from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.providers.factory import get_provider


class FakeProvider:
    def __init__(self, models: list[str] | None = None, list_models_error: Exception | None = None):
        self._models = models if models is not None else ["qwen2.5:14b-instruct", "llama3.1:8b-instruct", "bge-m3"]
        self._list_models_error = list_models_error

    async def list_models(self) -> list[str]:
        if self._list_models_error:
            raise self._list_models_error
        return self._models


async def _request(db_session, provider, method: str, **kwargs):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await getattr(client, method)("/settings/models", **kwargs)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_provider, None)


async def test_get_model_settings_returns_env_defaults_and_available_models(db_session):
    response = await _request(db_session, FakeProvider(), "get")

    assert response.status_code == 200
    body = response.json()
    assert body["default_model"] == settings.llm_model
    assert body["embeddings_model"] == settings.embedding_model
    assert body["chat_model"] is None
    assert body["extraction_model"] is None
    assert body["orchestration_model"] is None
    # bge-m3 is an embedding model, excluded from the LLM choices
    assert body["available_llm_models"] == ["qwen2.5:14b-instruct", "llama3.1:8b-instruct"]


async def test_get_model_settings_returns_503_when_runtime_is_unreachable(db_session):
    response = await _request(db_session, FakeProvider(list_models_error=ConnectionError("no route")), "get")

    assert response.status_code == 503


async def test_patch_sets_a_task_override(db_session):
    response = await _request(
        db_session, FakeProvider(), "patch", json={"chat_model": "llama3.1:8b-instruct"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["chat_model"] == "llama3.1:8b-instruct"
    assert body["extraction_model"] is None


async def test_patch_null_clears_an_override(db_session):
    await _request(db_session, FakeProvider(), "patch", json={"chat_model": "llama3.1:8b-instruct"})

    response = await _request(db_session, FakeProvider(), "patch", json={"chat_model": None})

    assert response.status_code == 200
    assert response.json()["chat_model"] is None


async def test_patch_default_model_to_null_is_rejected(db_session):
    response = await _request(db_session, FakeProvider(), "patch", json={"default_model": None})

    assert response.status_code == 400


async def test_patch_unknown_model_is_rejected(db_session):
    response = await _request(db_session, FakeProvider(), "patch", json={"chat_model": "made-up-model"})

    assert response.status_code == 400


async def test_patch_with_no_fields_is_rejected(db_session):
    response = await _request(db_session, FakeProvider(), "patch", json={})

    assert response.status_code == 400


async def test_patch_changes_persist_across_requests(db_session):
    await _request(db_session, FakeProvider(), "patch", json={"default_model": "llama3.1:8b-instruct"})

    response = await _request(db_session, FakeProvider(), "get")

    assert response.json()["default_model"] == "llama3.1:8b-instruct"
