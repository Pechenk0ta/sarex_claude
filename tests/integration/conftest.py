"""Integration tests run against a real Postgres (TEST_DATABASE_URL), migrated with Alembic.

Each test runs inside a transaction that is rolled back, so tests don't see each other's data.
"""

from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings


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
        db = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield db
        finally:
            await db.close()
            await transaction.rollback()
    await engine.dispose()
