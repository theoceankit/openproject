import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import engine
from app.providers.factory import get_provider


@pytest.fixture(autouse=True)
async def _dispose_engine_after_test():
    """asyncpg connections (and the cached provider's httpx client) are tied to the event
    loop they were created on, and pytest-asyncio uses a fresh loop per test; dispose/clear
    them so neither hands a stale, loop-bound connection to the next test's loop."""
    yield
    await engine.dispose()
    get_provider.cache_clear()


@pytest.fixture
async def db_session():
    """An AsyncSession bound to a transaction that is rolled back after the test.

    Disposes the engine's connection pool afterwards: asyncpg connections are tied to
    the event loop they were created on, and pytest-asyncio uses a fresh loop per test.
    """
    async with engine.connect() as connection:
        await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with session_factory() as session:
            yield session
        await connection.rollback()
    await engine.dispose()
