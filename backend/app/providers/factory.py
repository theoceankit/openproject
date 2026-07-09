from functools import lru_cache

from app.core.config import settings
from app.providers.base import ModelProvider
from app.providers.logging import LoggingProvider
from app.providers.ollama import OllamaProvider
from app.providers.usage import record_model_call_best_effort


@lru_cache
def get_provider() -> ModelProvider:
    """Return the configured model provider (global selection for Stage 1)."""
    provider: ModelProvider = OllamaProvider(
        host=settings.ollama_host,
        llm_model=settings.llm_model,
        embedding_model=settings.embedding_model,
        timeout=settings.ollama_timeout_seconds,
        record_usage=record_model_call_best_effort,
    )
    if settings.log_llm_interactions:
        provider = LoggingProvider(provider)
    return provider
