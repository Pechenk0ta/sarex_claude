import logging
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.db import SessionDep
from app.web import auth, refs
from app.web.deps import CurrentUser, LoginRequiredError
from app.web.templating import WEB_DIR, render

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title="Ознакомление с РД",
        docs_url=None if settings.is_prod else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_prod else "/api/openapi.json",
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key.get_secret_value(),
        session_cookie="rd_session",
        max_age=settings.session_max_age_hours * 3600,
        same_site="lax",
        https_only=settings.is_prod,
    )
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.include_router(auth.router)
    app.include_router(refs.router)

    @app.exception_handler(LoginRequiredError)
    async def login_required(request: Request, exc: LoginRequiredError) -> Response:
        target = request.url.path
        if request.url.query:
            target += f"?{request.url.query}"
        if request.method != "GET":
            target = "/"
        return RedirectResponse(f"/login?next={quote(target)}", status_code=303)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> Response:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return render(request, "error.html", status_code=exc.status_code, error=exc)

    @app.get("/")
    async def home(user: CurrentUser) -> RedirectResponse:
        # The board (stage 5) will live here; until then, open the directories.
        return RedirectResponse("/refs", status_code=303)

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


app: Any = create_app()
