import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk


class Project(UUIDPk, Timestamps, Base):
    """A construction project (ЖК or its phase), TZ 3.1."""

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(sa.String(255), unique=True)
    address: Mapped[str | None] = mapped_column(sa.String(500))
    project_manager_email: Mapped[str] = mapped_column(sa.String(320))
    is_active: Mapped[bool] = mapped_column(server_default=sa.true())

    corpuses: Mapped[list["Corpus"]] = relationship(
        back_populates="project", order_by="Corpus.name"
    )


class Corpus(UUIDPk, Timestamps, Base):
    """A building within a project, TZ 3.2."""

    __tablename__ = "corpuses"
    __table_args__ = (sa.UniqueConstraint("project_id", "name", name="uq_corpuses_project_name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(sa.String(255))
    is_active: Mapped[bool] = mapped_column(server_default=sa.true())

    project: Mapped[Project] = relationship(back_populates="corpuses")


class ProjectContractor(Base):
    """Plain list of a project's contractors, no contract binding, TZ 3.3."""

    __tablename__ = "project_contractors"

    project_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    contractor_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("contractors.id", ondelete="CASCADE"), primary_key=True, index=True
    )
