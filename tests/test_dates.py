from __future__ import annotations

from datetime import date, datetime, time

import pytest

from study.logic.dates import DateParseError, parse_date, parse_datetime

TODAY = date(2026, 11, 18)  # a Wednesday
NOW = datetime(2026, 11, 18, 14, 30)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-12-10", date(2026, 12, 10)),
        ("today", TODAY),
        ("Tomorrow", date(2026, 11, 19)),
        ("+3d", date(2026, 11, 21)),
        ("+2w", date(2026, 12, 2)),
        ("-5d", date(2026, 11, 13)),
        ("fri", date(2026, 11, 20)),
        ("friday", date(2026, 11, 20)),
        ("wed", date(2026, 11, 25)),  # never today: next week's Wednesday
        ("mon", date(2026, 11, 23)),
        ("12-10", date(2026, 12, 10)),
        ("1-15", date(2027, 1, 15)),  # already passed this year -> next year
        ("11-18", TODAY),
    ],
)
def test_parse_date(text: str, expected: date) -> None:
    assert parse_date(text, TODAY) == expected


@pytest.mark.parametrize("bad", ["soon", "2026-13-01", "2-30", "fr", "+3x"])
def test_unreadable_dates_explain_what_works(bad: str) -> None:
    with pytest.raises(DateParseError):
        parse_date(bad, TODAY)


def test_parse_datetime() -> None:
    assert parse_datetime("fri 23:59", NOW, time(9, 0)) == datetime(2026, 11, 20, 23, 59)
    assert parse_datetime("2026-12-10 9:00", NOW, time(23, 59)) == datetime(2026, 12, 10, 9, 0)
    assert parse_datetime("2026-12-10T09:00", NOW, time(23, 59)) == datetime(2026, 12, 10, 9, 0)
    assert parse_datetime("tomorrow", NOW, time(23, 59)) == datetime(2026, 11, 19, 23, 59)
    with pytest.raises(DateParseError, match="time of day"):
        parse_datetime("fri 25:00", NOW, time(9, 0))
