"""Tests for the calendar event schemas."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from planner.calendar.models import Event, EventChanges, NewEvent

ZURICH = ZoneInfo("Europe/Zurich")


def make_event(**overrides: object) -> Event:
    fields: dict[str, object] = {
        "id": "e1",
        "title": "Lecture",
        "start": datetime(2026, 11, 23, 9, 0, tzinfo=UTC),
        "end": datetime(2026, 11, 23, 10, 0, tzinfo=UTC),
    }
    fields.update(overrides)
    return Event.model_validate(fields)


def test_zurich_time_is_stored_as_utc() -> None:
    event = make_event(
        start=datetime(2026, 11, 23, 10, 0, tzinfo=ZURICH),
        end=datetime(2026, 11, 23, 11, 0, tzinfo=ZURICH),
    )
    assert event.start == datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
    assert event.start.tzinfo == UTC


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        make_event(start=datetime(2026, 11, 23, 9, 0))


@pytest.mark.parametrize("minutes", [0, -30])
def test_end_must_be_after_start(minutes: int) -> None:
    start = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
    with pytest.raises(ValidationError, match="end must be after start"):
        make_event(start=start, end=start + timedelta(minutes=minutes))


def test_empty_title_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_event(title="")


def test_unknown_field_is_rejected() -> None:
    # A typo like "titel" must not be silently ignored.
    with pytest.raises(ValidationError, match="titel"):
        make_event(titel="Lecture")


def test_events_are_immutable() -> None:
    event = make_event()
    with pytest.raises(ValidationError):
        event.title = "Changed"  # type: ignore[misc]


def test_event_across_spring_forward_is_one_hour() -> None:
    # 01:30 -> 03:30 local on 2026-03-29 looks like 2 hours but is 1 hour,
    # because 02:00-03:00 does not exist that night. UTC gets this right.
    event = make_event(
        start=datetime(2026, 3, 29, 1, 30, tzinfo=ZURICH),
        end=datetime(2026, 3, 29, 3, 30, tzinfo=ZURICH),
    )
    assert event.end - event.start == timedelta(hours=1)


def test_new_event_defaults() -> None:
    new = NewEvent(
        title="Study",
        start=datetime(2026, 11, 23, 9, 0, tzinfo=UTC),
        end=datetime(2026, 11, 23, 10, 0, tzinfo=UTC),
    )
    assert new.plan_id is None


def test_event_changes_default_to_no_change() -> None:
    assert EventChanges().model_dump(exclude_unset=True) == {}
