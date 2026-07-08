import json
import logging
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.chat.pipeline import answer_question
from app.core.config import settings
from app.core.logging import request_id_var
from app.ingestion.pipeline import ingest_file
from app.main import app
from app.providers.logging import LoggingProvider
from tests.test_chat import FakeProvider, make_document_with_chunk, make_vector


class FakeWrappedProvider:
    def __init__(self, response: str = "answer", error: Exception | None = None):
        self.response = response
        self.error = error

    async def generate(self, prompt, *, system=None, format=None, call_site=None):
        if self.error:
            raise self.error
        return self.response

    async def embed(self, texts, *, call_site=None):
        if self.error:
            raise self.error
        return [make_vector() for _ in texts]


async def test_logging_provider_logs_generate_call(caplog):
    provider = LoggingProvider(FakeWrappedProvider(response="hello"))

    with caplog.at_level(logging.INFO, logger="app.llm"):
        result = await provider.generate(
            "prompt text", system="sys prompt", format={"title": "SomeSchema"}, call_site="chat"
        )

    assert result == "hello"
    [record] = [r for r in caplog.records if r.name == "app.llm"]
    entry = json.loads(record.getMessage())
    assert entry["operation"] == "generate"
    assert entry["call_site"] == "chat"
    assert entry["prompt"] == "prompt text"
    assert entry["system"] == "sys prompt"
    assert entry["format"] == "SomeSchema"
    assert entry["response"] == "hello"
    assert entry["model"] == settings.llm_model
    assert isinstance(entry["duration_ms"], (int, float))


async def test_logging_provider_logs_generate_error(caplog):
    provider = LoggingProvider(FakeWrappedProvider(error=RuntimeError("boom")))

    with caplog.at_level(logging.INFO, logger="app.llm"):
        with pytest.raises(RuntimeError):
            await provider.generate("prompt", call_site="chat")

    [record] = [r for r in caplog.records if r.name == "app.llm"]
    entry = json.loads(record.getMessage())
    assert entry["error"] == "boom"
    assert "response" not in entry


async def test_logging_provider_logs_embed_call(caplog):
    provider = LoggingProvider(FakeWrappedProvider())

    with caplog.at_level(logging.INFO, logger="app.llm"):
        result = await provider.embed(["a", "b"], call_site="ingestion")

    assert len(result) == 2
    [record] = [r for r in caplog.records if r.name == "app.llm"]
    entry = json.loads(record.getMessage())
    assert entry["operation"] == "embed"
    assert entry["call_site"] == "ingestion"
    assert entry["texts"] == ["a", "b"]
    assert entry["embedding_count"] == 2
    assert entry["model"] == settings.embedding_model


async def test_logging_provider_includes_current_request_id(caplog):
    token = request_id_var.set("req-123")
    try:
        provider = LoggingProvider(FakeWrappedProvider())
        with caplog.at_level(logging.INFO, logger="app.llm"):
            await provider.generate("prompt", call_site="chat")
    finally:
        request_id_var.reset(token)

    [record] = [r for r in caplog.records if r.name == "app.llm"]
    entry = json.loads(record.getMessage())
    assert entry["request_id"] == "req-123"


async def test_logging_provider_logs_truncated_preview(caplog, monkeypatch):
    monkeypatch.setattr(settings, "log_llm_preview_chars", 10)
    provider = LoggingProvider(FakeWrappedProvider(response="a fairly long response text"))

    with caplog.at_level(logging.INFO, logger="app.llm_preview"):
        await provider.generate("a fairly long prompt text", call_site="chat")

    [record] = [r for r in caplog.records if r.name == "app.llm_preview"]
    message = record.getMessage()
    assert "generate[chat]" in message
    assert "prompt='a fairly l...'" in message
    assert "response='a fairly l...'" in message


async def test_logging_provider_logs_generate_error_preview(caplog):
    provider = LoggingProvider(FakeWrappedProvider(error=RuntimeError("boom")))

    with caplog.at_level(logging.INFO, logger="app.llm_preview"):
        with pytest.raises(RuntimeError):
            await provider.generate("prompt", call_site="chat")

    [record] = [r for r in caplog.records if r.name == "app.llm_preview"]
    assert "error: boom" in record.getMessage()


async def test_logging_provider_logs_embed_preview(caplog):
    provider = LoggingProvider(FakeWrappedProvider())

    with caplog.at_level(logging.INFO, logger="app.llm_preview"):
        await provider.embed(["a", "b"], call_site="ingestion")

    [record] = [r for r in caplog.records if r.name == "app.llm_preview"]
    message = record.getMessage()
    assert "embed[ingestion]" in message
    assert "2 text(s) -> 2 embedding(s)" in message


async def test_sql_queries_are_logged_when_enabled(db_session, caplog, monkeypatch):
    monkeypatch.setattr(settings, "log_sql_queries", True)

    with caplog.at_level(logging.INFO, logger="app.db.queries"):
        await db_session.execute(text("SELECT 1"))

    records = [r for r in caplog.records if r.name == "app.db.queries"]
    assert any("SELECT 1" in r.getMessage() for r in records)


async def test_sql_queries_are_not_logged_by_default(db_session, caplog):
    with caplog.at_level(logging.INFO, logger="app.db.queries"):
        await db_session.execute(text("SELECT 1"))

    assert [r for r in caplog.records if r.name == "app.db.queries"] == []


async def test_request_middleware_logs_request_with_id(caplog):
    with caplog.at_level(logging.INFO, logger="app.requests"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    [record] = [r for r in caplog.records if r.name == "app.requests"]
    assert "GET /health -> 200" in record.getMessage()


async def test_ingest_file_logs_document_status(db_session, tmp_path: Path, caplog):
    file_path = tmp_path / "doc.md"
    file_path.write_text("# Title\n\nSome content")

    provider = FakeWrappedProvider()

    with caplog.at_level(logging.INFO, logger="app.ingestion"):
        result = await ingest_file(db_session, provider, file_path)

    assert result["status"] == "ingested"
    records = [r for r in caplog.records if r.name == "app.ingestion"]
    assert any("ingested" in r.getMessage() for r in records)


async def test_answer_question_logs_conversation_outcome(db_session, caplog):
    await make_document_with_chunk(db_session)
    provider = FakeProvider(query_embedding=make_vector((0, 1.0)), answer="A SKU is a Stock Keeping Unit [1].")

    with caplog.at_level(logging.INFO, logger="app.chat"):
        outcome = await answer_question(db_session, provider, "What is a SKU?")

    records = [r for r in caplog.records if r.name == "app.chat"]
    assert any(str(outcome.conversation_id) in r.getMessage() and "answered" in r.getMessage() for r in records)
