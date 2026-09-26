import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk
from app.models.enums import UserRole, str_enum


class User(UUIDPk, Timestamps, Base):
    """Coordinator or administrator, TZ 3.6. Contractors and PMs are not users."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(sa.String(320), unique=True)
    full_name: Mapped[str] = mapped_column(sa.String(255))
    password_hash: Mapped[str | None] = mapped_column(sa.String(255))
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole, "user_role"))
    is_active: Mapped[bool] = mapped_column(server_default=sa.true())
