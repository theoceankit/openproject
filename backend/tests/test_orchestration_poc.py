import uuid

import pytest
from sqlalchemy import text

from app.db.session import engine
from app.orchestration.poc import resume_poc, start_poc


async def _checkpoint_row_exists(thread_id: str) -> bool:
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT 1 FROM checkpoints WHERE thread_id = :tid LIMIT 1"), {"tid": thread_id}
        )
        return result.first() is not None


async def _cleanup_checkpoint_rows(thread_id: str) -> None:
    async with engine.begin() as connection:
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            await connection.execute(text(f"DELETE FROM {table} WHERE thread_id = :tid"), {"tid": thread_id})


class _RecordingProvider:
    def __init__(self) -> None:
        self.generate_calls: list[dict] = []
        self.embed_calls: list[dict] = []

    async def generate(self, prompt, *, system=None, format=None, model=None, call_site=None):
        self.generate_calls.append({"prompt": prompt, "call_site": call_site})
        return "fake response"

    async def embed(self, texts, *, call_site=None):
        self.embed_calls.append({"texts": texts, "call_site": call_site})
        return [[0.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
async def thread_id():
    tid = str(uuid.uuid4())
    yield tid
    await _cleanup_checkpoint_rows(tid)


async def test_start_poc_pauses_with_interrupt_payload(thread_id):
    result = await start_poc(thread_id)

    assert "question" in result
    assert "result" not in result


async def test_pause_is_durable_in_postgres_not_memory(thread_id):
    await start_poc(thread_id)

    assert await _checkpoint_row_exists(thread_id)


async def test_resume_with_fresh_objects_completes_the_run(thread_id):
    # start_poc and resume_poc each build their own graph and checkpointer (per spec);
    # calling them as separate awaited calls already exercises "fresh objects, same
    # process" resumption, since neither call may share in-memory state with the other.
    await start_poc(thread_id)

    result = await resume_poc(thread_id, "abc123")

    assert result["result"] == "done:abc123"


async def test_finalize_calls_provider_through_sanctioned_helper_with_call_site(monkeypatch, thread_id):
    fake = _RecordingProvider()
    monkeypatch.setattr("app.orchestration.providers.get_provider", lambda: fake)

    await start_poc(thread_id)
    await resume_poc(thread_id, "xyz")

    calls = fake.generate_calls + fake.embed_calls
    assert len(calls) == 1
    [call] = calls
    assert call["call_site"]
    assert call["call_site"].endswith(":finalize")


async def test_resuming_an_already_completed_thread_is_idempotent(thread_id):
    await start_poc(thread_id)
    first = await resume_poc(thread_id, "once")
    assert first["result"] == "done:once"

    # Contract: resuming a finished thread again returns the already-completed state
    # unchanged rather than reprocessing the new value or raising.
    second = await resume_poc(thread_id, "ignored")
    assert second["result"] == "done:once"
