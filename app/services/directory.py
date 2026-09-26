"""Directories: projects, corpuses, contractors and the production calendar (TZ 3.1–3.3, 3.7)."""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contractor, Corpus, Holiday, Notification, Project, ProjectContractor
from app.services.errors import ValidationError
from app.services.validation import clean_email, clean_optional_text, clean_text

# --- projects -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectRow:
    project: Project
    corpus_count: int
    contractor_count: int
    notification_count: int


async def list_projects(session: AsyncSession) -> list[ProjectRow]:
    corpuses = select(func.count()).where(Corpus.project_id == Project.id).scalar_subquery()
    contractors = (
        select(func.count()).where(ProjectContractor.project_id == Project.id).scalar_subquery()
    )
    notifications = (
        select(func.count()).where(Notification.project_id == Project.id).scalar_subquery()
    )
    rows = await session.execute(
        select(Project, corpuses, contractors, notifications).order_by(
            Project.is_active.desc(), Project.name
        )
    )
    return [ProjectRow(*row) for row in rows.all()]


@dataclass(frozen=True)
class CorpusRow:
    corpus: Corpus
    notification_count: int


@dataclass(frozen=True)
class ProjectDetails:
    project: Project
    corpuses: list[CorpusRow]
    contractors: list[Contractor]
    available_contractors: list[Contractor]


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> ProjectDetails | None:
    project = await session.get(Project, project_id)
    if project is None:
        return None
    counts = select(func.count()).where(Notification.corpus_id == Corpus.id).scalar_subquery()
    corpus_rows = await session.execute(
        select(Corpus, counts).where(Corpus.project_id == project_id).order_by(Corpus.name)
    )
    linked = list(
        await session.scalars(
            select(Contractor)
            .join(ProjectContractor, ProjectContractor.contractor_id == Contractor.id)
            .where(ProjectContractor.project_id == project_id)
            .order_by(Contractor.name)
        )
    )
    linked_ids = {c.id for c in linked}
    everyone = await session.scalars(select(Contractor).order_by(Contractor.name))
    return ProjectDetails(
        project=project,
        corpuses=[CorpusRow(*row) for row in corpus_rows.all()],
        contractors=linked,
        available_contractors=[c for c in everyone if c.id not in linked_ids],
    )


async def _check_project_name(
    session: AsyncSession, name: str, exclude: uuid.UUID | None = None
) -> None:
    query = select(Project.id).where(func.lower(Project.name) == name.lower())
    if exclude is not None:
        query = query.where(Project.id != exclude)
    if await session.scalar(query):
        raise ValidationError("Проект с таким названием уже есть.", "name")


async def create_project(
    session: AsyncSession, name: str, address: str | None, project_manager_email: str
) -> Project:
    name = clean_text(name, "name", "Наименование")
    await _check_project_name(session, name)
    project = Project(
        name=name,
        address=clean_optional_text(address),
        project_manager_email=clean_email(project_manager_email, "project_manager_email"),
    )
    session.add(project)
    await session.flush()
    return project


async def update_project(
    session: AsyncSession,
    project: Project,
    name: str,
    address: str | None,
    project_manager_email: str,
    is_active: bool,
) -> None:
    name = clean_text(name, "name", "Наименование")
    await _check_project_name(session, name, exclude=project.id)
    project.name = name
    project.address = clean_optional_text(address)
    project.project_manager_email = clean_email(project_manager_email, "project_manager_email")
    project.is_active = is_active
    await session.flush()


# --- corpuses -------------------------------------------------------------------------------


async def _check_corpus_name(
    session: AsyncSession, project_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None
) -> None:
    query = select(Corpus.id).where(
        Corpus.project_id == project_id, func.lower(Corpus.name) == name.lower()
    )
    if exclude is not None:
        query = query.where(Corpus.id != exclude)
    if await session.scalar(query):
        raise ValidationError("В проекте уже есть корпус с таким названием.", "corpus_name")


async def add_corpus(session: AsyncSession, project: Project, name: str) -> Corpus:
    name = clean_text(name, "corpus_name", "Наименование корпуса")
    await _check_corpus_name(session, project.id, name)
    corpus = Corpus(project_id=project.id, name=name)
    session.add(corpus)
    await session.flush()
    return corpus


async def get_corpus(
    session: AsyncSession, project_id: uuid.UUID, corpus_id: uuid.UUID
) -> Corpus | None:
    return await session.scalar(
        select(Corpus).where(Corpus.id == corpus_id, Corpus.project_id == project_id)
    )


async def update_corpus(session: AsyncSession, corpus: Corpus, name: str, is_active: bool) -> None:
    name = clean_text(name, "corpus_name", "Наименование корпуса")
    await _check_corpus_name(session, corpus.project_id, name, exclude=corpus.id)
    corpus.name = name
    corpus.is_active = is_active
    await session.flush()


async def delete_corpus(session: AsyncSession, corpus: Corpus) -> None:
    used = await session.scalar(
        select(func.count()).select_from(Notification).where(Notification.corpus_id == corpus.id)
    )
    if used:
        raise ValidationError("По корпусу уже есть уведомления: его можно только отключить.")
    await session.delete(corpus)
    await session.flush()


# --- contractors ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractorRow:
    contractor: Contractor
    project_names: list[str]


async def list_contractors(session: AsyncSession) -> list[ContractorRow]:
    contractors = list(await session.scalars(select(Contractor).order_by(Contractor.name)))
    links = await session.execute(
        select(ProjectContractor.contractor_id, Project.name)
        .join(Project, Project.id == ProjectContractor.project_id)
        .order_by(Project.name)
    )
    names: dict[uuid.UUID, list[str]] = {}
    for contractor_id, project_name in links.all():
        names.setdefault(contractor_id, []).append(project_name)
    return [ContractorRow(c, names.get(c.id, [])) for c in contractors]


async def _check_contractor(
    session: AsyncSession, name: str, email: str, exclude: uuid.UUID | None = None
) -> None:
    for column, value, field, message in (
        (Contractor.name, name, "name", "Подрядчик с таким названием уже есть."),
        (Contractor.email, email, "email", "Этот email уже указан у другого подрядчика."),
    ):
        query = select(Contractor.id).where(func.lower(column) == value.lower())
        if exclude is not None:
            query = query.where(Contractor.id != exclude)
        if await session.scalar(query):
            raise ValidationError(message, field)


async def create_contractor(session: AsyncSession, name: str, email: str) -> Contractor:
    name = clean_text(name, "name", "Организация")
    email = clean_email(email)
    await _check_contractor(session, name, email)
    contractor = Contractor(name=name, email=email)
    session.add(contractor)
    await session.flush()
    return contractor


async def update_contractor(
    session: AsyncSession, contractor: Contractor, name: str, email: str
) -> None:
    name = clean_text(name, "name", "Организация")
    email = clean_email(email)
    await _check_contractor(session, name, email, exclude=contractor.id)
    contractor.name = name
    contractor.email = email
    await session.flush()


async def link_contractor(
    session: AsyncSession, project: Project, contractor_id: uuid.UUID
) -> None:
    if await session.get(Contractor, contractor_id) is None:
        raise ValidationError("Выберите подрядчика из списка.", "contractor_id")
    if await session.get(ProjectContractor, (project.id, contractor_id)) is None:
        session.add(ProjectContractor(project_id=project.id, contractor_id=contractor_id))
        await session.flush()


async def unlink_contractor(
    session: AsyncSession, project: Project, contractor_id: uuid.UUID
) -> None:
    await session.execute(
        delete(ProjectContractor).where(
            ProjectContractor.project_id == project.id,
            ProjectContractor.contractor_id == contractor_id,
        )
    )


# --- production calendar --------------------------------------------------------------------


async def list_holidays(session: AsyncSession, year: int) -> list[Holiday]:
    result = await session.scalars(
        select(Holiday)
        .where(Holiday.date.between(date(year, 1, 1), date(year, 12, 31)))
        .order_by(Holiday.date)
    )
    return list(result)


async def set_holiday(session: AsyncSession, day: date, is_workday: bool) -> None:
    """Add or change a calendar exception."""
    weekend = day.weekday() >= 5
    if is_workday and not weekend:
        raise ValidationError("Будний день и так рабочий: отмечать его не нужно.", "date")
    if not is_workday and weekend:
        raise ValidationError("Суббота и воскресенье и так выходные: отмечать их не нужно.", "date")
    holiday = await session.get(Holiday, day)
    if holiday is None:
        session.add(Holiday(date=day, is_workday=is_workday))
    else:
        holiday.is_workday = is_workday
    await session.flush()


async def delete_holiday(session: AsyncSession, day: date) -> None:
    await session.execute(delete(Holiday).where(Holiday.date == day))
