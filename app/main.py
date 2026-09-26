import logging

from fastapi import FastAPI, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db import SessionDep

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title="Ознакомление с РД",
        docs_url="/api/docs" if settings.app_env != "prod" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.app_env != "prod" else None,
    )

    @app.get("/health")
    async def health(response: Response, session: SessionDep) -> dict[str, str]:
        try:
            await session.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError):
            logger.exception("Database health check failed")
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "error", "db": "unavailable"}
        return {"status": "ok", "db": "ok"}

    return app


app = create_app()
