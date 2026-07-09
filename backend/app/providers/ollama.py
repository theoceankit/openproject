import asyncio

from ollama import AsyncClient

from app.providers.base import ModelProvider


class OllamaProvider(ModelProvider):
    """Local model runtime provider, the default per model-providers.mdx.

    Ollama serves one generation at a time on a typical single-GPU/CPU local setup, so
    concurrent callers (e.g. several "save to memory" clicks) would otherwise each open
    their own request and independently race the same fixed timeout while queued behind
    each other inside Ollama, timing out even though the model itself responds in time.
    A semaphore serializes calls at the client so a request's timeout clock only starts
    once it actually begins, not while it waits its turn.
    """

    def __init__(self, host: str, llm_model: str, embedding_model: str, timeout: float | None = None) -> None:
        self._client = AsyncClient(host=host, timeout=timeout)
        self._llm_model = llm_model
        self._embedding_model = embedding_model
        self._lock = asyncio.Semaphore(1)

    async def generate(
        self, prompt: str, *, system: str | None = None, format: dict | None = None, call_site: str | None = None
    ) -> str:
        async with self._lock:
            response = await self._client.generate(
                model=self._llm_model, prompt=prompt, system=system, format=format
            )
        return response.response

    async def embed(self, texts: list[str], *, call_site: str | None = None) -> list[list[float]]:
        async with self._lock:
            response = await self._client.embed(model=self._embedding_model, input=texts)
        return [list(vector) for vector in response.embeddings]
