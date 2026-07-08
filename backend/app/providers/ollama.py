from ollama import AsyncClient

from app.providers.base import ModelProvider


class OllamaProvider(ModelProvider):
    """Local model runtime provider, the default per model-providers.mdx."""

    def __init__(self, host: str, llm_model: str, embedding_model: str, timeout: float | None = None) -> None:
        self._client = AsyncClient(host=host, timeout=timeout)
        self._llm_model = llm_model
        self._embedding_model = embedding_model

    async def generate(
        self, prompt: str, *, system: str | None = None, format: dict | None = None, call_site: str | None = None
    ) -> str:
        response = await self._client.generate(model=self._llm_model, prompt=prompt, system=system, format=format)
        return response.response

    async def embed(self, texts: list[str], *, call_site: str | None = None) -> list[list[float]]:
        response = await self._client.embed(model=self._embedding_model, input=texts)
        return [list(vector) for vector in response.embeddings]
