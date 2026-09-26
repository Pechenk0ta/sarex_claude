import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk


class Contractor(UUIDPk, Timestamps, Base):
    """A contractor organisation, TZ 3.3. Projects are linked via `project_contractors`."""

    __tablename__ = "contractors"

    name: Mapped[str] = mapped_column(sa.String(255), unique=True)
    email: Mapped[str] = mapped_column(sa.String(320), unique=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(sa.String(64))
