"""Tests for FakeCalendar, which also check the CalendarBackend contract."""

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from planner.calendar.backend import (
    CalendarBackend,
    EventNotFoundError,
    NotOwnedError,
)
from planner.calendar.fake import FakeCalendar
from planner.calendar.models import Event, EventChanges, NewEvent

ZURICH = ZoneInfo("Europe/Zurich")


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


LECTURE = Event(id="lecture", title="Lecture", start=utc(23, 9), end=utc(23, 11))


@pytest.fixture
def cal() -> FakeCalendar:
    return FakeCalendar([LECTURE])


def test_fake_calendar_fits_the_interface() -> None:
    # mypy checks this line: it fails type checking if a method is missing
    # or has the wrong signature.
    backend: CalendarBackend = FakeCalendar()
    assert backend.list_events(utc(23, 0), utc(24, 0)) == []


# --- list_events ---


@pytest.mark.parametrize(
    ("start", "end", "found"),
    [
        (utc(23, 8), utc(23, 12), True),  # range covers the event
        (utc(23, 10), utc(23, 10, 30), True),  # range inside the event
        (utc(23, 8), utc(23, 9, 15), True),  # partial overlap at the start
        (utc(23, 11), utc(23, 12), False),  # range starts exactly when event ends
        (utc(23, 8), utc(23, 9), False),  # range ends exactly when event starts
    ],
)
def test_list_events_overlap(
    cal: FakeCalendar, start: datetime, end: datetime, found: bool
) -> None:
    assert (cal.list_events(start, end) == [LECTURE]) is found


def test_list_events_sorted_by_start(cal: FakeCalendar) -> None:
    early = cal.create_event(NewEvent(title="Gym", start=utc(23, 7), end=utc(23, 8)))
    events = cal.list_events(utc(23, 0), utc(24, 0))
    assert [e.id for e in events] == [early.id, "lecture"]


def test_list_events_accepts_zurich_times(cal: FakeCalendar) -> None:
    # 10:00-12:00 Zurich is 09:00-11:00 UTC in November.
    start = datetime(2026, 11, 23, 10, 0, tzinfo=ZURICH)
    end = datetime(2026, 11, 23, 12, 0, tzinfo=ZURICH)
    assert cal.list_events(start, end) == [LECTURE]


def test_list_events_rejects_naive_times(cal: FakeCalendar) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        cal.list_events(datetime(2026, 11, 23), utc(24, 0))


# --- create_event ---


def test_created_events_are_owned_and_listed(cal: FakeCalendar) -> None:
    new = NewEvent(title="Study", start=utc(23, 13), end=utc(23, 14), plan_id="p1")
    created = cal.create_event(new)
    assert created.created_by_planner
    assert created.plan_id == "p1"
    assert created in cal.list_events(utc(23, 0), utc(24, 0))


def test_ids_are_unique_and_deterministic() -> None:
    cal = FakeCalendar(
        [Event(id="fake-1", title="x", start=utc(23, 9), end=utc(23, 10))]
    )
    new = NewEvent(title="Study", start=utc(23, 13), end=utc(23, 14))
    ids = [cal.create_event(new).id for _ in range(2)]
    assert ids == ["fake-2", "fake-3"]  # skips the existing "fake-1"


# --- update_event ---


def test_update_own_event(cal: FakeCalendar) -> None:
    created = cal.create_event(
        NewEvent(title="Study", start=utc(23, 13), end=utc(23, 14))
    )
    updated = cal.update_event(
        created.id, EventChanges(title="Revise", end=utc(23, 15))
    )
    assert (updated.title, updated.start, updated.end) == (
        "Revise",
        utc(23, 13),
        utc(23, 15),
    )
    assert updated.created_by_planner


def test_invalid_update_is_rejected_and_event_unchanged(cal: FakeCalendar) -> None:
    created = cal.create_event(
        NewEvent(title="Study", start=utc(23, 13), end=utc(23, 14))
    )
    with pytest.raises(ValidationError, match="end must be after start"):
        cal.update_event(created.id, EventChanges(start=utc(23, 15)))
    assert cal.list_events(utc(23, 0), utc(24, 0))[-1] == created


# --- ownership and unknown ids ---


def test_cannot_update_or_delete_users_events(cal: FakeCalendar) -> None:
    with pytest.raises(NotOwnedError):
        cal.update_event("lecture", EventChanges(title="Hacked"))
    with pytest.raises(NotOwnedError):
        cal.delete_event("lecture")
    assert cal.list_events(utc(23, 0), utc(24, 0)) == [LECTURE]


def test_unknown_id_raises(cal: FakeCalendar) -> None:
    with pytest.raises(EventNotFoundError):
        cal.update_event("nope", EventChanges(title="x"))
    with pytest.raises(EventNotFoundError):
        cal.delete_event("nope")


def test_delete_own_event(cal: FakeCalendar) -> None:
    created = cal.create_event(
        NewEvent(title="Study", start=utc(23, 13), end=utc(23, 14))
    )
    cal.delete_event(created.id)
    assert cal.list_events(utc(23, 0), utc(24, 0)) == [LECTURE]


# --- loading ---


def test_from_json(tmp_path: Path) -> None:
    path = tmp_path / "week.json"
    path.write_text(
        '[{"id": "a", "title": "Gym", "start": "2026-11-24T18:00:00+01:00",'
        ' "end": "2026-11-24T19:00:00+01:00"}]'
    )
    cal = FakeCalendar.from_json(path)
    [event] = cal.list_events(utc(24, 0), utc(25, 0))
    assert event.start == utc(24, 17)  # converted to UTC
    assert not event.created_by_planner  # loaded events belong to the user


def test_duplicate_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        FakeCalendar([LECTURE, LECTURE])
