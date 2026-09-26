from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.db import SessionDep
from app.models import User, UserRole
from app.services.users import get_active_user
from app.web.session import logout, session_user_id


class LoginRequiredError(Exception):
    """Handled in main.py: redirect to the login page."""


async def current_user(request: Request, session: SessionDep) -> User:
    user_id = session_user_id(request)
    user = await get_active_user(session, user_id) if user_id else None
    if user is None:
        logout(request)
        raise LoginRequiredError
    request.state.user = user
    return user


async def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role is not UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Действие доступно только администратору.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
AdminUser = Annotated[User, Depends(admin_user)]
