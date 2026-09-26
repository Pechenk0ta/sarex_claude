from collections.abc import AsyncIterator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import get_session
from app.main import create_app


async def test_health_ok_when_database_is_reachable() -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


async def test_health_503_when_database_is_down() -> None:
    engine = create_async_engine("postgresql+asyncpg://nobody:x@127.0.0.1:1/none")
    sessions = async_sessionmaker(engine)

    async def broken_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = broken_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    await engine.dispose()

    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": "unavailable"}
