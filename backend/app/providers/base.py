from abc import ABC, abstractmethod


class ModelProvider(ABC):
    """A pluggable source of the two model operations the backend needs."""

    @abstractmethod
    async def generate(
        self, prompt: str, *, system: str | None = None, format: dict | None = None, call_site: str | None = None
    ) -> str:
        """Produce a chat or extraction response from a prompt.

        If `format` is given, it is a JSON schema the response must conform to. `call_site`
        identifies the calling code for logging (see `app.providers.logging.LoggingProvider`)
        and has no effect on the request sent to the model.
        """

    @abstractmethod
    async def embed(self, texts: list[str], *, call_site: str | None = None) -> list[list[float]]:
        """Produce an embedding vector for each input text."""
