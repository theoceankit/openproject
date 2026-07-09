from sqlalchemy import select

from app.db.models import ModelCall
from app.providers.usage import record_model_call, record_model_call_best_effort


async def test_record_model_call_inserts_a_row(db_session):
    await record_model_call(
        db_session,
        operation="generate",
        call_site="chat",
        model="qwen2.5:14b-instruct",
        prompt_tokens=100,
        completion_tokens=20,
    )

    rows = (await db_session.execute(select(ModelCall))).scalars().all()
    assert len(rows) == 1
    assert rows[0].operation == "generate"
    assert rows[0].call_site == "chat"
    assert rows[0].model == "qwen2.5:14b-instruct"
    assert rows[0].prompt_tokens == 100
    assert rows[0].completion_tokens == 20


async def test_record_model_call_best_effort_swallows_errors(monkeypatch):
    class ExplodingSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        def add(self, obj):
            raise RuntimeError("db is down")

    monkeypatch.setattr("app.providers.usage.async_session", lambda: ExplodingSession())

    # Must not raise: usage stats are best-effort telemetry, a DB hiccup here must not fail
    # the generate()/embed() call that triggered it.
    await record_model_call_best_effort(
        operation="generate", call_site="chat", model="qwen2.5:14b-instruct", prompt_tokens=1, completion_tokens=1
    )
