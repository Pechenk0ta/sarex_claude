from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contractor, Corpus, Project, ProjectContractor, User, UserRole
from app.services.users import create_user


async def project_with_contractors(
    session: AsyncSession, contractors: int = 3
) -> tuple[Project, Corpus, list[Contractor], User]:
    project = Project(name="ЖК «Тест»", project_manager_email="pm@company.ru")
    corpus = Corpus(project=project, name="Корпус 1")
    people = [Contractor(name=f"ООО «П{i}»", email=f"p{i}@example.ru") for i in range(contractors)]
    user = await create_user(
        session, "coord@example.ru", "Смирнова Анна", UserRole.COORDINATOR, "coord-password-1"
    )
    session.add_all([project, corpus, *people])
    await session.flush()
    session.add_all(ProjectContractor(project_id=project.id, contractor_id=c.id) for c in people)
    await session.flush()
    return project, corpus, people, user
