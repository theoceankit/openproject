import asyncio

from ollama._types import EmbedResponse, GenerateResponse, ListResponse

from app.providers.factory import get_provider
from app.providers.logging import LoggingProvider
from app.providers.ollama import OllamaProvider


class FakeOllamaClient:
    def __init__(self) -> None:
        self.generate_calls: list[dict] = []
        self.embed_calls: list[dict] = []

    async def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return GenerateResponse(response="generated text")

    async def embed(self, **kwargs):
        self.embed_calls.append(kwargs)
        return EmbedResponse(embeddings=[[0.1, 0.2, 0.3]])

    async def list(self):
        return ListResponse(models=[ListResponse.Model(model="qwen2.5:14b-instruct"), ListResponse.Model(model="bge-m3")])


class SlowFakeOllamaClient:
    """Tracks how many generate() calls are in flight at once, like a single-worker Ollama."""

    def __init__(self) -> None:
        self.max_concurrent = 0
        self._current = 0

    async def generate(self, **kwargs):
        self._current += 1
        self.max_concurrent = max(self.max_concurrent, self._current)
        await asyncio.sleep(0.05)
        self._current -= 1
        return GenerateResponse(response="generated text")


def make_provider() -> tuple[OllamaProvider, FakeOllamaClient]:
    provider = OllamaProvider(host="http://localhost:11434", llm_model="test-llm", embedding_model="test-embed")
    fake_client = FakeOllamaClient()
    provider._client = fake_client
    return provider, fake_client


async def test_generate_calls_configured_model_and_returns_text():
    provider, fake_client = make_provider()

    result = await provider.generate("hello", system="be terse")

    assert result == "generated text"
    assert fake_client.generate_calls == [
        {"model": "test-llm", "prompt": "hello", "system": "be terse", "format": None}
    ]


async def test_generate_model_override_replaces_configured_model():
    provider, fake_client = make_provider()

    await provider.generate("hello", model="other-model")

    assert fake_client.generate_calls == [
        {"model": "other-model", "prompt": "hello", "system": None, "format": None}
    ]


async def test_list_models_returns_model_names():
    provider, _ = make_provider()

    result = await provider.list_models()

    assert result == ["qwen2.5:14b-instruct", "bge-m3"]


async def test_embed_calls_configured_model_and_returns_vectors():
    provider, fake_client = make_provider()

    result = await provider.embed(["a", "b"])

    assert result == [[0.1, 0.2, 0.3]]
    assert fake_client.embed_calls == [{"model": "test-embed", "input": ["a", "b"]}]


async def test_generate_calls_are_serialized_against_concurrent_callers():
    provider, fake_client = make_provider()
    provider._client = SlowFakeOllamaClient()

    await asyncio.gather(*(provider.generate(f"prompt {i}") for i in range(4)))

    assert provider._client.max_concurrent == 1


def test_get_provider_returns_cached_provider():
    provider = get_provider()

    assert isinstance(provider, LoggingProvider)
    assert isinstance(provider._wrapped, OllamaProvider)
    assert get_provider() is provider
