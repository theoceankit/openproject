from abc import ABC, abstractmethod


class ModelProvider(ABC):
    """A pluggable source of the two model operations the backend needs."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        format: dict | None = None,
        model: str | None = None,
        call_site: str | None = None,
    ) -> str:
        """Produce a chat or extraction response from a prompt.

        If `format` is given, it is a JSON schema the response must conform to. `model`
        overrides the provider's configured default model for this call (see
        `app.model_settings.service.resolve_model`); omit it to use that default. `call_site`
        identifies the calling code for logging (see `app.providers.logging.LoggingProvider`)
        and has no effect on the request sent to the model.
        """

    @abstractmethod
    async def embed(self, texts: list[str], *, call_site: str | None = None) -> list[list[float]]:
        """Produce an embedding vector for each input text."""

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return the names of models currently available to this provider."""
