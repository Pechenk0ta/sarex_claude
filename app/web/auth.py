from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.auth.ratelimit import login_limiter
from app.db import SessionDep
from app.services.users import authenticate
from app.web.session import login, logout, verify_csrf
from app.web.templating import render

router = APIRouter()


def _safe_next(target: str | None) -> str:
    """Only local paths, so the login form can't redirect to another site."""
    if not target:
        return "/"
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith("/") or target.startswith("//"):
        return "/"
    return target


@router.get("/login")
async def login_page(request: Request, next: str | None = None) -> Any:
    return render(request, "login.html", next=_safe_next(next), email="", error=None)


@router.post("/login", dependencies=[Depends(verify_csrf)])
async def login_submit(
    request: Request,
    session: SessionDep,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
) -> Any:
    ip = request.client.host if request.client else "unknown"
    keys = [f"email:{email.strip().lower()}", f"ip:{ip}"]
    wait = login_limiter.blocked_for(keys)
    if wait:
        return render(
            request,
            "login.html",
            status_code=429,
            next=_safe_next(next),
            email=email,
            error=f"Слишком много неудачных попыток входа. Попробуйте через {wait // 60 + 1} мин.",
        )
    user = await authenticate(session, email, password)
    if user is None:
        login_limiter.failed(keys)
        return render(
            request,
            "login.html",
            status_code=400,
            next=_safe_next(next),
            email=email,
            error="Неверный email или пароль. Проверьте раскладку и попробуйте ещё раз.",
        )
    login_limiter.succeeded(keys)
    login(request, user.id)
    return RedirectResponse(_safe_next(next), status_code=303)


@router.post("/logout", dependencies=[Depends(verify_csrf)])
async def logout_submit(request: Request) -> RedirectResponse:
    logout(request)
    return RedirectResponse("/login", status_code=303)
