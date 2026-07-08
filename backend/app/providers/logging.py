import json
import logging
import time

from app.core.config import settings
from app.core.logging import request_id_var
from app.providers.base import ModelProvider

llm_logger = logging.getLogger("app.llm")
# Not "app.llm.preview": that would be a child of "app.llm", which has propagate=False and a
# llm.jsonl handler, so records would land in llm.jsonl (malformed) instead of the console/app.log.
preview_logger = logging.getLogger("app.llm_preview")


def _preview(text: str) -> str:
    """Collapse whitespace and truncate to `log_llm_preview_chars` for console/app.log output."""
    collapsed = " ".join(text.split())
    limit = settings.log_llm_preview_chars
    return collapsed if len(collapsed) <= limit else collapsed[:limit] + "..."


class LoggingProvider(ModelProvider):
    """Wraps a ModelProvider, logging each call's prompt, response, and timing to `app.llm`."""

    def __init__(self, wrapped: ModelProvider) -> None:
        self._wrapped = wrapped

    async def generate(
        self, prompt: str, *, system: str | None = None, format: dict | None = None, call_site: str | None = None
    ) -> str:
        start = time.monotonic()
        entry = {
            "operation": "generate",
            "call_site": call_site,
            "model": settings.llm_model,
            "system": system,
            "prompt": prompt,
            "format": format.get("title") if format else None,
        }
        try:
            response = await self._wrapped.generate(prompt, system=system, format=format, call_site=call_site)
        except Exception as exc:
            self._log({**entry, "error": str(exc)}, start)
            raise
        self._log({**entry, "response": response}, start)
        return response

    async def embed(self, texts: list[str], *, call_site: str | None = None) -> list[list[float]]:
        start = time.monotonic()
        entry = {
            "operation": "embed",
            "call_site": call_site,
            "model": settings.embedding_model,
            "texts": texts,
        }
        try:
            result = await self._wrapped.embed(texts, call_site=call_site)
        except Exception as exc:
            self._log({**entry, "error": str(exc)}, start)
            raise
        self._log({**entry, "embedding_count": len(result)}, start)
        return result

    def _log(self, fields: dict, start: float) -> None:
        entry = {
            "request_id": request_id_var.get(),
            "duration_ms": round((time.monotonic() - start) * 1000, 1),
            **fields,
        }
        llm_logger.info(json.dumps(entry, ensure_ascii=False))

        call = f"{entry['operation']}[{entry['call_site']}] {entry['model']} ({entry['duration_ms']} ms)"
        if entry["operation"] == "generate":
            if "error" in entry:
                preview_logger.info("%s prompt=%r -> error: %s", call, _preview(entry["prompt"]), entry["error"])
            else:
                preview_logger.info(
                    "%s prompt=%r -> response=%r", call, _preview(entry["prompt"]), _preview(entry["response"])
                )
        else:
            if "error" in entry:
                preview_logger.info("%s %d text(s) -> error: %s", call, len(entry["texts"]), entry["error"])
            else:
                preview_logger.info(
                    "%s %d text(s) -> %d embedding(s)", call, len(entry["texts"]), entry["embedding_count"]
                )
