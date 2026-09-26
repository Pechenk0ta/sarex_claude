"""Users: coordinators and administrators (TZ 3.6)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import MIN_PASSWORD_LENGTH, hash_password, verify_password
from app.models import User, UserRole
from app.services.errors import ValidationError
from app.services.validation import clean_email, clean_text


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    hash_ = user.password_hash if user is not None and user.is_active else None
    if not verify_password(password, hash_) or user is None:
        return None
    return user


async def get_active_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.scalar(select(User).where(User.id == user_id, User.is_active))


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.scalars(select(User).order_by(User.is_active.desc(), User.full_name))
    return list(result)


def check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов.", "password"
        )


async def create_user(
    session: AsyncSession, email: str, full_name: str, role: UserRole, password: str
) -> User:
    email = clean_email(email)
    full_name = clean_text(full_name, "full_name", "ФИО")
    check_password(password)
    if await session.scalar(select(User.id).where(User.email == email)):
        raise ValidationError("Пользователь с таким email уже есть.", "email")
    user = User(email=email, full_name=full_name, role=role, password_hash=hash_password(password))
    session.add(user)
    await session.flush()
    return user


async def set_password(session: AsyncSession, user: User, password: str) -> None:
    check_password(password)
    user.password_hash = hash_password(password)
    await session.flush()


async def set_active(session: AsyncSession, user: User, active: bool, acting: User) -> None:
    if not active and user.id == acting.id:
        raise ValidationError("Нельзя отключить собственную учётную запись.")
    if not active and user.role is UserRole.ADMIN:
        admins = await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == UserRole.ADMIN, User.is_active)
        )
        if (admins or 0) <= 1:
            raise ValidationError("Нельзя отключить последнего администратора.")
    user.is_active = active
    await session.flush()
