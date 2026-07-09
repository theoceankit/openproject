import asyncio
from collections.abc import Awaitable, Callable

from ollama import AsyncClient

from app.providers.base import ModelProvider

RecordUsage = Callable[..., Awaitable[None]]


class OllamaProvider(ModelProvider):
    """Local model runtime provider, the default per model-providers.mdx.

    Ollama serves one generation at a time on a typical single-GPU/CPU local setup, so
    concurrent callers (e.g. several "save to memory" clicks) would otherwise each open
    their own request and independently race the same fixed timeout while queued behind
    each other inside Ollama, timing out even though the model itself responds in time.
    A semaphore serializes calls at the client so a request's timeout clock only starts
    once it actually begins, not while it waits its turn.
    """

    def __init__(
        self,
        host: str,
        llm_model: str,
        embedding_model: str,
        timeout: float | None = None,
        record_usage: RecordUsage | None = None,
    ) -> None:
        self._client = AsyncClient(host=host, timeout=timeout)
        self._llm_model = llm_model
        self._embedding_model = embedding_model
        self._lock = asyncio.Semaphore(1)
        # None by default so constructing a provider directly (e.g. in tests) never touches the
        # database; app.providers.factory wires the real recorder for the production singleton.
        self._record_usage = record_usage

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        format: dict | None = None,
        model: str | None = None,
        call_site: str | None = None,
    ) -> str:
        resolved_model = model or self._llm_model
        async with self._lock:
            response = await self._client.generate(model=resolved_model, prompt=prompt, system=system, format=format)
        if self._record_usage is not None:
            await self._record_usage(
                operation="generate",
                call_site=call_site,
                model=resolved_model,
                prompt_tokens=response.prompt_eval_count,
                completion_tokens=response.eval_count,
            )
        return response.response

    async def embed(self, texts: list[str], *, call_site: str | None = None) -> list[list[float]]:
        async with self._lock:
            response = await self._client.embed(model=self._embedding_model, input=texts)
        if self._record_usage is not None:
            await self._record_usage(
                operation="embed",
                call_site=call_site,
                model=self._embedding_model,
                prompt_tokens=response.prompt_eval_count,
                completion_tokens=response.eval_count,
            )
        return [list(vector) for vector in response.embeddings]

    async def list_models(self) -> list[str]:
        response = await self._client.list()
        return [model.model for model in response.models if model.model]
