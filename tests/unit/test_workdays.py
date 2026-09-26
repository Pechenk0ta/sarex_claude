from datetime import UTC, date, datetime

import pytest

from app.services.workdays import add_workdays, is_workday, local_date, workdays_between

NO_EXCEPTIONS: dict[date, bool] = {}

# Examples in the style of the Russian production calendar.
CALENDAR_2026 = {
    date(2026, 1, 1): False,
    date(2026, 1, 2): False,
    date(2026, 1, 5): False,
    date(2026, 1, 6): False,
    date(2026, 1, 7): False,
    date(2026, 1, 8): False,
    date(2026, 5, 1): False,
    date(2026, 5, 11): False,
    date(2026, 11, 4): False,
    date(2026, 12, 31): False,
}


class TestIsWorkday:
    def test_weekdays_and_weekends_without_exceptions(self) -> None:
        assert is_workday(date(2026, 9, 25), NO_EXCEPTIONS)  # Friday
        assert not is_workday(date(2026, 9, 26), NO_EXCEPTIONS)  # Saturday
        assert not is_workday(date(2026, 9, 27), NO_EXCEPTIONS)  # Sunday

    def test_holiday_on_weekday_is_day_off(self) -> None:
        assert not is_workday(date(2026, 11, 4), CALENDAR_2026)  # Wednesday

    def test_transferred_saturday_is_workday(self) -> None:
        assert is_workday(date(2026, 10, 31), {date(2026, 10, 31): True})


class TestAddWorkdays:
    def test_deadline_from_mockup(self) -> None:
        # Sent Fri 11.09, 10 working days -> Fri 25.09.
        assert add_workdays(date(2026, 9, 11), 10, NO_EXCEPTIONS) == date(2026, 9, 25)

    def test_first_reminder_after_friday_is_monday(self) -> None:
        assert add_workdays(date(2026, 9, 11), 1, NO_EXCEPTIONS) == date(2026, 9, 14)

    def test_sent_on_weekend_counts_from_monday(self) -> None:
        assert add_workdays(date(2026, 9, 26), 1, NO_EXCEPTIONS) == date(2026, 9, 28)

    def test_zero_days_is_same_date(self) -> None:
        assert add_workdays(date(2026, 9, 11), 0, NO_EXCEPTIONS) == date(2026, 9, 11)

    def test_holiday_inside_period_extends_it(self) -> None:
        # Mon 02.11 + 3 wd: Tue 03.11, (Wed 04.11 holiday), Thu 05.11, Fri 06.11.
        assert add_workdays(date(2026, 11, 2), 3, CALENDAR_2026) == date(2026, 11, 6)

    def test_across_new_year_holidays(self) -> None:
        # Wed 30.12.2026 + 1 wd: 31.12, 01.01 and 04.01 off, 02–03.01 weekend -> Tue 05.01.2027.
        calendar = {**CALENDAR_2026, date(2027, 1, 1): False, date(2027, 1, 4): False}
        assert add_workdays(date(2026, 12, 30), 1, calendar) == date(2027, 1, 5)

    def test_across_month_boundary(self) -> None:
        assert add_workdays(date(2026, 9, 29), 3, NO_EXCEPTIONS) == date(2026, 10, 2)

    def test_transferred_workday_is_counted(self) -> None:
        # Fri 30.10 + 1 wd, Sat 31.10 made a working day -> 31.10.
        assert add_workdays(date(2026, 10, 30), 1, {date(2026, 10, 31): True}) == date(2026, 10, 31)

    def test_negative_count_rejected(self) -> None:
        with pytest.raises(ValueError):
            add_workdays(date(2026, 9, 11), -1, NO_EXCEPTIONS)

    def test_calendar_without_workdays_does_not_hang(self) -> None:
        with pytest.raises(ValueError):
            add_workdays(date(2026, 9, 11), 1, _AllDaysOff())


class TestWorkdaysBetween:
    def test_elapsed_days_from_mockup(self) -> None:
        # Sent 11.09, today Sat 26.09 -> 10 working days passed.
        assert workdays_between(date(2026, 9, 11), date(2026, 9, 26), NO_EXCEPTIONS) == 10

    def test_same_day_and_reverse_are_zero(self) -> None:
        assert workdays_between(date(2026, 9, 11), date(2026, 9, 11), NO_EXCEPTIONS) == 0
        assert workdays_between(date(2026, 9, 26), date(2026, 9, 11), NO_EXCEPTIONS) == 0

    def test_holidays_are_not_counted(self) -> None:
        # Tue 03.11 .. Fri 06.11 without Wed 04.11.
        assert workdays_between(date(2026, 11, 2), date(2026, 11, 6), CALENDAR_2026) == 3

    def test_consistent_with_add_workdays(self) -> None:
        start = date(2026, 12, 25)
        for count in range(0, 15):
            end = add_workdays(start, count, CALENDAR_2026)
            assert workdays_between(start, end, CALENDAR_2026) == count


class TestLocalDate:
    def test_late_evening_utc_is_next_day_in_moscow(self) -> None:
        moment = datetime(2026, 9, 25, 22, 30, tzinfo=UTC)  # 01:30 on 26.09 in Moscow
        assert local_date(moment, "Europe/Moscow") == date(2026, 9, 26)

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValueError):
            local_date(datetime(2026, 9, 25, 12, 0), "Europe/Moscow")


class _AllDaysOff(dict[date, bool]):
    def __contains__(self, key: object) -> bool:
        return True

    def __getitem__(self, key: date) -> bool:
        return False
