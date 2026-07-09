from app.core.config import settings
from app.model_settings.service import (
    get_or_create,
    is_embedding_model,
    list_available_llm_models,
    resolve_model,
)


class FakeProvider:
    def __init__(self, models: list[str]):
        self._models = models

    async def list_models(self) -> list[str]:
        return self._models


async def test_get_or_create_seeds_default_model_from_env_config_on_first_access(db_session):
    row = await get_or_create(db_session)

    assert row.default_model == settings.llm_model
    assert row.chat_model is None
    assert row.extraction_model is None
    assert row.orchestration_model is None


async def test_get_or_create_returns_the_same_row_on_repeated_calls(db_session):
    first = await get_or_create(db_session)
    second = await get_or_create(db_session)

    assert first.id == second.id


async def test_resolve_model_falls_back_to_default_when_no_override_is_set(db_session):
    model = await resolve_model(db_session, "chat")

    assert model == settings.llm_model


async def test_resolve_model_returns_the_task_override_when_set(db_session):
    row = await get_or_create(db_session)
    row.chat_model = "llama3.1:8b-instruct"
    await db_session.flush()

    assert await resolve_model(db_session, "chat") == "llama3.1:8b-instruct"
    assert await resolve_model(db_session, "extraction") == settings.llm_model


async def test_is_embedding_model_recognizes_common_embedding_families():
    assert is_embedding_model("bge-m3")
    assert is_embedding_model("nomic-embed-text")
    assert is_embedding_model("all-minilm")
    assert not is_embedding_model("qwen2.5:14b-instruct")
    assert not is_embedding_model("llama3.1:8b-instruct")


async def test_list_available_llm_models_excludes_embedding_models():
    provider = FakeProvider(["qwen2.5:14b-instruct", "bge-m3", "llama3.1:8b-instruct", "nomic-embed-text"])

    result = await list_available_llm_models(provider)

    assert result == ["qwen2.5:14b-instruct", "llama3.1:8b-instruct"]
