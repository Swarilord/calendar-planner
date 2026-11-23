"""Tests for the solver's slot grid."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from planner.calendar.models import Event
from planner.parser.schemas import PlanRequest, Task, Window
from planner.solver.grid import build_grid

ZURICH = ZoneInfo("Europe/Zurich")


def z(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=ZURICH)


def request(start: datetime, end: datetime, **extra: object) -> PlanRequest:
    task = Task(name="Analysis", duration_min=60, deadline=end)
    return PlanRequest.model_validate(
        {"horizon_start": start, "horizon_end": end, "tasks": [task], **extra}
    )


# --- slots and local days ---


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        ((11, 23), 96),  # ordinary day: 24h
        ((3, 29), 92),  # spring switch: 23h
        ((10, 25), 100),  # autumn switch: 25h
    ],
)
def test_one_local_day_has_real_number_of_slots(
    day: tuple[int, int], expected: int
) -> None:
    month, d = day
    grid = build_grid(request(z(month, d, 0), z(month, d + 1, 0)), [])
    assert grid.n_slots == expected
    assert set(grid.local_days) == {date(2026, month, d)}


def test_slots_are_utc_and_15_minutes_apart() -> None:
    grid = build_grid(request(z(11, 23, 9), z(11, 23, 10)), [])
    assert grid.starts == [
        datetime(2026, 11, 23, 8, m, tzinfo=UTC) for m in (0, 15, 30, 45)
    ]


def test_horizon_is_rounded_inward_to_whole_slots() -> None:
    grid = build_grid(request(z(11, 23, 9, 7), z(11, 23, 10, 5)), [])
    assert grid.starts[0] == z(11, 23, 9, 15)
    assert grid.end(grid.n_slots - 1) == z(11, 23, 10)


# --- busy slots ---


def test_event_marks_every_slot_it_touches() -> None:
    event = Event(
        id="e", title="Lecture", start=z(11, 23, 10, 5), end=z(11, 23, 10, 50)
    )
    grid = build_grid(request(z(11, 23, 9, 45), z(11, 23, 11, 15)), [event])
    # slots: 9:45, 10:00, 10:15, 10:30, 10:45, 11:00
    assert grid.busy == [False, True, True, True, True, False]


def test_event_ending_at_slot_start_does_not_mark_it() -> None:
    event = Event(id="e", title="Lecture", start=z(11, 23, 9), end=z(11, 23, 10))
    grid = build_grid(request(z(11, 23, 9, 45), z(11, 23, 10, 15)), [event])
    assert grid.busy == [True, False]


def test_blocked_window_marks_slots() -> None:
    window = Window(start=z(11, 25, 18), end=z(11, 25, 18, 30))
    grid = build_grid(
        request(z(11, 25, 17, 45), z(11, 25, 18, 45), blocked=[window]), []
    )
    assert grid.in_blocked_window == [False, True, True, False]


# --- day hours ---


@pytest.mark.parametrize("month_day", [(11, 23), (7, 6), (3, 29), (10, 25)])
def test_day_hours_follow_local_clock_all_year(month_day: tuple[int, int]) -> None:
    month, d = month_day
    req = request(
        z(month, d, 0), z(month, d + 1, 0), day_start=time(9), day_end=time(17)
    )
    grid = build_grid(req, [])
    allowed = [
        s for s, out in zip(grid.starts, grid.outside_day_hours, strict=True) if not out
    ]
    assert allowed[0] == z(month, d, 9)
    assert grid.end(grid.starts.index(allowed[-1])) == z(month, d, 17)
    assert len(allowed) == 8 * 4


def test_no_day_end_allows_slot_up_to_midnight() -> None:
    req = request(z(11, 23, 23, 30), z(11, 24, 0, 30), day_start=time(9))
    grid = build_grid(req, [])
    # 23:30, 23:45 allowed; 00:00, 00:15 are before 9:00 on Tuesday
    assert grid.outside_day_hours == [False, False, True, True]


# --- deadline and earliest start as slot indices ---


def test_deadline_slot_counts_only_slots_that_finish_in_time() -> None:
    grid = build_grid(request(z(11, 23, 9), z(11, 23, 12)), [])
    assert grid.slots_ending_by(z(11, 23, 10)) == 4  # 9:00 .. 9:45
    assert grid.slots_ending_by(z(11, 23, 10, 10)) == 4  # 10:00 slot ends 10:15
    assert grid.slots_ending_by(z(11, 23, 8)) == 0


def test_first_slot_from_rounds_up() -> None:
    grid = build_grid(request(z(11, 23, 9), z(11, 23, 12)), [])
    assert grid.first_slot_from(z(11, 23, 9, 30)) == 2
    assert grid.first_slot_from(z(11, 23, 9, 20)) == 2  # 9:15 slot starts too early
    assert grid.first_slot_from(z(11, 23, 13)) == grid.n_slots
