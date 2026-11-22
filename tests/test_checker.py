"""Tests for the independent schedule checker."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from planner.calendar.models import Event
from planner.checker.check import ViolationKind, check
from planner.common import overlaps
from planner.parser.schemas import PlanRequest, Task
from planner.schedule import Schedule, ScheduledBlock

ZURICH = ZoneInfo("Europe/Zurich")


def z(day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in Zurich time in the week of Mon 23 Nov 2026."""
    return datetime(2026, 11, day, hour, minute, tzinfo=ZURICH)


REQUEST = PlanRequest(
    horizon_start=z(23, 0),
    horizon_end=z(30, 0),
    tasks=[Task(name="Analysis", duration_min=120, deadline=z(26, 23, 59))],
)
LECTURE = Event(id="lecture", title="Lecture", start=z(23, 9), end=z(23, 11))


def kinds(*blocks: tuple[str, datetime, datetime]) -> list[ViolationKind]:
    schedule = Schedule(
        blocks=[ScheduledBlock(task_name=n, start=s, end=e) for n, s, e in blocks]
    )
    return [v.kind for v in check(REQUEST, [LECTURE], schedule)]


# --- the shared overlap rule ---


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ((9, 11), (10, 12), True),  # partial overlap
        ((9, 11), (9, 11), True),  # identical
        ((9, 12), (10, 11), True),  # one inside the other
        ((9, 11), (11, 12), False),  # touching: a ends when b starts
        ((11, 12), (9, 11), False),  # touching, other order
        ((9, 10), (11, 12), False),  # apart
    ],
)
def test_overlaps(a: tuple[int, int], b: tuple[int, int], expected: bool) -> None:
    assert overlaps(z(23, a[0]), z(23, a[1]), z(23, b[0]), z(23, b[1])) is expected


# --- valid schedules ---


def test_empty_schedule_has_no_violations() -> None:
    assert kinds() == []


def test_valid_block_has_no_violations() -> None:
    assert kinds(("Analysis", z(23, 13), z(23, 15))) == []


def test_blocks_touching_an_event_are_fine() -> None:
    # Ends exactly when the lecture starts, and starts exactly when it ends.
    assert (
        kinds(("Analysis", z(23, 8), z(23, 9)), ("Analysis", z(23, 11), z(23, 12)))
        == []
    )


def test_block_ending_exactly_at_deadline_is_fine() -> None:
    assert kinds(("Analysis", z(26, 21, 59), z(26, 23, 59))) == []


# --- each violation kind ---


def test_unknown_task() -> None:
    assert kinds(("Gym", z(23, 13), z(23, 14))) == [ViolationKind.UNKNOWN_TASK]


def test_clash_with_event() -> None:
    assert kinds(("Analysis", z(23, 10), z(23, 12))) == [
        ViolationKind.CLASHES_WITH_EVENT
    ]


def test_clash_between_blocks() -> None:
    assert kinds(
        ("Analysis", z(23, 13), z(23, 15)), ("Analysis", z(23, 14), z(23, 16))
    ) == [ViolationKind.CLASHES_WITH_BLOCK]


def test_after_deadline() -> None:
    assert kinds(("Analysis", z(26, 23), z(27, 0))) == [ViolationKind.AFTER_DEADLINE]


@pytest.mark.parametrize(
    ("start", "end"),
    [(z(22, 23), z(23, 1)), (z(29, 23), z(30, 1))],  # crosses the start / the end
)
def test_outside_horizon(start: datetime, end: datetime) -> None:
    found = kinds(("Analysis", start, end))
    assert ViolationKind.OUTSIDE_HORIZON in found


def test_reports_every_violation_not_just_the_first() -> None:
    # After the deadline AND clashing with an event (a lecture added on Friday).
    friday_lecture = Event(id="fri", title="Lecture", start=z(27, 9), end=z(27, 11))
    schedule = Schedule(
        blocks=[ScheduledBlock(task_name="Analysis", start=z(27, 10), end=z(27, 12))]
    )
    found = {v.kind for v in check(REQUEST, [friday_lecture], schedule)}
    assert found == {ViolationKind.AFTER_DEADLINE, ViolationKind.CLASHES_WITH_EVENT}


def test_message_names_the_problem() -> None:
    schedule = Schedule(
        blocks=[ScheduledBlock(task_name="Analysis", start=z(23, 10), end=z(23, 12))]
    )
    [violation] = check(REQUEST, [LECTURE], schedule)
    assert "Lecture" in violation.message and "Analysis" in violation.message
