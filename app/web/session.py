"""Signed-cookie session helpers: login state, CSRF token, flash messages."""

import secrets
import uuid

from fastapi import HTTPException, Request, status

_USER_KEY = "user_id"
_CSRF_KEY = "csrf"
_FLASH_KEY = "flash"


def login(request: Request, user_id: uuid.UUID) -> None:
    request.session.clear()  # new session on login
    request.session[_USER_KEY] = str(user_id)


def logout(request: Request) -> None:
    request.session.clear()


def session_user_id(request: Request) -> uuid.UUID | None:
    raw = request.session.get(_USER_KEY)
    try:
        return uuid.UUID(raw) if raw else None
    except ValueError:
        return None


def csrf_token(request: Request) -> str:
    token = request.session.get(_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[_CSRF_KEY] = token
    return str(token)


async def verify_csrf(request: Request) -> None:
    """Dependency for every form POST."""
    form = await request.form()
    sent = form.get("csrf_token")
    expected = request.session.get(_CSRF_KEY)
    if not isinstance(sent, str) or not expected or not secrets.compare_digest(sent, expected):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Форма устарела. Обновите страницу и повторите."
        )


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session.setdefault(_FLASH_KEY, []).append([kind, message])


def pop_flashes(request: Request) -> list[list[str]]:
    return list(request.session.pop(_FLASH_KEY, []))
