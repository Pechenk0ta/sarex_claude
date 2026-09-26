import datetime as dt

from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Holiday(Base):
    """Exception to the normal Mon–Fri week, TZ 3.7."""

    __tablename__ = "holidays"

    date: Mapped[dt.date] = mapped_column(primary_key=True)
    # False: holiday on a weekday; True: a weekend day that became a working day.
    is_workday: Mapped[bool]
