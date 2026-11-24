"""Tests for the independent schedule checker."""

from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

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
    # No default limits: each test switches on only the rule it is about.
    day_start=None,
    max_work_min_per_day=None,
)
LECTURE = Event(id="lecture", title="Lecture", start=z(23, 9), end=z(23, 11))


def kinds(*blocks: tuple[str, datetime, datetime]) -> list[ViolationKind]:
    """Violation kinds for these blocks, ignoring WRONG_TOTAL (tested separately)."""
    schedule = Schedule(
        blocks=[ScheduledBlock(task_name=n, start=s, end=e) for n, s, e in blocks]
    )
    return [
        v.kind
        for v in check(REQUEST, [LECTURE], schedule)
        if v.kind != ViolationKind.WRONG_TOTAL  # most tests check one rule only
    ]


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


# --- allowed hours (step 3.2) ---


def request_with(**overrides: Any) -> PlanRequest:
    """REQUEST with some fields replaced, validated again."""
    return PlanRequest.model_validate(REQUEST.model_dump() | overrides)


def kinds_for(
    request: PlanRequest, *blocks: tuple[str, datetime, datetime]
) -> list[ViolationKind]:
    schedule = Schedule(
        blocks=[ScheduledBlock(task_name=n, start=s, end=e) for n, s, e in blocks]
    )
    return [
        v.kind
        for v in check(request, [], schedule)
        if v.kind != ViolationKind.WRONG_TOTAL  # most tests check one rule only
    ]


NINE_TO_22 = request_with(day_start=time(9, 0), day_end=time(22, 0))


@pytest.mark.parametrize(
    ("start", "end", "ok"),
    [
        (z(24, 9), z(24, 10), True),  # starts exactly at day_start
        (z(24, 21), z(24, 22), True),  # ends exactly at day_end
        (z(24, 8, 30), z(24, 9, 30), False),  # starts before 9
        (z(24, 21, 30), z(24, 22, 30), False),  # ends after 22
        (z(24, 23), z(25, 1), False),  # crosses midnight
    ],
)
def test_day_hours(start: datetime, end: datetime, ok: bool) -> None:
    found = kinds_for(NINE_TO_22, ("Analysis", start, end))
    assert (ViolationKind.OUTSIDE_DAY_HOURS not in found) is ok


def test_only_day_start_still_forbids_crossing_midnight() -> None:
    # Without day_end the day runs to midnight; 00:00-01:00 is before day_start.
    request = request_with(day_start=time(9, 0))
    assert kinds_for(request, ("Analysis", z(24, 23), z(25, 1))) == [
        ViolationKind.OUTSIDE_DAY_HOURS
    ]


def test_no_day_hours_allows_any_time() -> None:
    assert kinds_for(REQUEST, ("Analysis", z(24, 23), z(25, 1))) == []


def dst_request(day: int, month: int) -> PlanRequest:
    """A request around a daylight-saving switch, with 'nothing before 9'."""
    return PlanRequest(
        horizon_start=datetime(2026, month, day - 2, tzinfo=ZURICH),
        horizon_end=datetime(2026, month, day + 2, tzinfo=ZURICH),
        tasks=[
            Task(
                name="Analysis",
                duration_min=60,
                deadline=datetime(2026, month, day + 2, tzinfo=ZURICH),
            )
        ],
        day_start=time(9, 0),
    )


@pytest.mark.parametrize(
    ("month", "switch_day", "block_day", "ok"),
    [
        # Spring forward (29 Mar): 07:30 UTC is 08:30 the day before, 09:30 on the day.
        (3, 29, 28, False),
        (3, 29, 29, True),
        # Fall back (25 Oct): 07:30 UTC is 09:30 the day before, 08:30 on the day.
        (10, 25, 24, True),
        (10, 25, 25, False),
    ],
)
def test_day_start_follows_daylight_saving(
    month: int, switch_day: int, block_day: int, ok: bool
) -> None:
    # The SAME UTC time gets opposite verdicts on either side of a switch.
    start = datetime(2026, month, block_day, 7, 30, tzinfo=UTC)
    end = start + timedelta(hours=1)
    found = kinds_for(dst_request(switch_day, month), ("Analysis", start, end))
    assert (ViolationKind.OUTSIDE_DAY_HOURS not in found) is ok


def test_blocked_window() -> None:
    wednesday_evening = {"start": z(25, 18), "end": z(25, 23, 59)}
    request = request_with(blocked=[wednesday_evening])
    assert kinds_for(request, ("Analysis", z(25, 19), z(25, 20))) == [
        ViolationKind.IN_BLOCKED_WINDOW
    ]
    # Touching the window is fine.
    assert kinds_for(request, ("Analysis", z(25, 17), z(25, 18))) == []


def test_earliest_start() -> None:
    released_tuesday = Task(
        name="Analysis",
        duration_min=120,
        deadline=z(26, 23, 59),
        earliest_start=z(24, 12),
    )
    request = request_with(tasks=[released_tuesday.model_dump()])
    assert kinds_for(request, ("Analysis", z(24, 11), z(24, 13))) == [
        ViolationKind.BEFORE_EARLIEST_START
    ]
    assert kinds_for(request, ("Analysis", z(24, 12), z(24, 14))) == []  # boundary


def test_day_end_midnight_is_rejected_by_schema() -> None:
    with pytest.raises(ValidationError, match="ambiguous"):
        request_with(day_end=time(0, 0))


# --- amounts (step 3.3) ---


def all_kinds(
    request: PlanRequest, *blocks: tuple[str, datetime, datetime]
) -> list[ViolationKind]:
    """Every violation kind, WRONG_TOTAL included."""
    schedule = Schedule(
        blocks=[ScheduledBlock(task_name=n, start=s, end=e) for n, s, e in blocks]
    )
    return [v.kind for v in check(request, [], schedule)]


def with_task(**task_fields: Any) -> PlanRequest:
    task = {"name": "Analysis", "duration_min": 120, "deadline": z(26, 23, 59)}
    return request_with(tasks=[task | task_fields])


def test_block_too_short() -> None:
    # 120 min split as 15 + 105, with the default 30-minute minimum block.
    found = all_kinds(
        with_task(),
        ("Analysis", z(23, 13), z(23, 13, 15)),
        ("Analysis", z(24, 13), z(24, 14, 45)),
    )
    assert found == [ViolationKind.BLOCK_TOO_SHORT]


def test_short_task_may_use_a_short_block() -> None:
    # A 15-minute task can't need 30-minute blocks: its minimum becomes 15.
    request = with_task(duration_min=15)
    assert all_kinds(request, ("Analysis", z(23, 13), z(23, 13, 15))) == []


def test_block_too_long() -> None:
    request = with_task(max_block_min=60)
    assert all_kinds(request, ("Analysis", z(23, 13), z(23, 15))) == [
        ViolationKind.BLOCK_TOO_LONG
    ]


@pytest.mark.parametrize(
    ("blocks", "message"),
    [
        ([], "0 of 120"),  # nothing scheduled
        ([("Analysis", z(23, 13), z(23, 14))], "60 of 120"),  # too little
        ([("Analysis", z(23, 13), z(23, 16))], "180 of 120"),  # too much
    ],
)
def test_wrong_total(
    blocks: list[tuple[str, datetime, datetime]], message: str
) -> None:
    schedule = Schedule(
        blocks=[ScheduledBlock(task_name=n, start=s, end=e) for n, s, e in blocks]
    )
    [violation] = check(REQUEST, [], schedule)
    assert violation.kind == ViolationKind.WRONG_TOTAL
    assert message in violation.message


def test_total_split_over_several_blocks_is_fine() -> None:
    assert (
        all_kinds(
            REQUEST,
            ("Analysis", z(23, 13), z(23, 14)),
            ("Analysis", z(24, 9), z(24, 10)),
        )
        == []
    )


def test_daily_cap() -> None:
    request = request_with(max_work_min_per_day=90)
    # 120 minutes on Monday breaks a 90-minute cap; split over two days it is fine.
    assert all_kinds(request, ("Analysis", z(23, 13), z(23, 15))) == [
        ViolationKind.DAILY_CAP_EXCEEDED
    ]
    assert (
        all_kinds(
            request,
            ("Analysis", z(23, 13), z(23, 14)),
            ("Analysis", z(24, 13), z(24, 14)),
        )
        == []
    )


def test_daily_cap_splits_blocks_at_local_midnight() -> None:
    # 23:00-01:00 is 60 minutes on each day, so a 60-minute cap holds.
    request = request_with(max_work_min_per_day=60)
    assert all_kinds(request, ("Analysis", z(23, 23), z(24, 1))) == []


def test_daily_cap_counts_real_minutes_on_dst_day() -> None:
    # On 29 Mar 2026, 01:00-04:00 local is only 2 real hours (02:00-03:00 is skipped).
    def mar(day: int, hour: int) -> datetime:
        return datetime(2026, 3, day, hour, tzinfo=ZURICH)

    request = PlanRequest(
        horizon_start=mar(28, 0),
        horizon_end=mar(31, 0),
        tasks=[Task(name="Analysis", duration_min=120, deadline=mar(31, 0))],
        max_work_min_per_day=150,
        day_start=None,  # the block is at night; this test is about the cap
    )
    assert all_kinds(request, ("Analysis", mar(29, 1), mar(29, 4))) == []
