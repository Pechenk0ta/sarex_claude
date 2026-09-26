"""Integration tests run against a real Postgres (TEST_DATABASE_URL), migrated with Alembic.

Each test runs inside a transaction that is rolled back, so tests don't see each other's data.
"""

from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.ratelimit import login_limiter
from app.config import get_settings
from app.db import get_session
from app.main import create_app


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[str]:
    url = get_settings().database_url
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield url


@pytest.fixture
async def session(migrated_database: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(migrated_database)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        db = AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield db
        finally:
            await db.close()
            await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = test_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture(autouse=True)
def _reset_login_limiter() -> Iterator[None]:
    login_limiter._failures.clear()
    yield
    login_limiter._failures.clear()
