"""Tests for the CP-SAT solver. The independent checker is the referee."""

import random
from collections.abc import Sequence
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from planner.calendar.models import Event
from planner.checker.check import check
from planner.parser.schemas import PlanRequest, Task, Window
from planner.schedule import Schedule
from planner.solver.model import SolveStatus, solve

ZURICH = ZoneInfo("Europe/Zurich")


def z(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=ZURICH)


def task(name: str, minutes: int, deadline: datetime, **extra: object) -> Task:
    fields = {"name": name, "duration_min": minutes, "deadline": deadline}
    return Task.model_validate({**fields, **extra})


def solved(request: PlanRequest, events: Sequence[Event] = ()) -> Schedule:
    """Solve, and assert the checker finds nothing wrong with the result."""
    result = solve(request, events)
    assert result.status == SolveStatus.OPTIMAL
    assert result.schedule is not None
    assert check(request, events, result.schedule) == []
    return result.schedule


def used(schedule: Schedule) -> list[tuple[datetime, datetime]]:
    return [(b.start, b.end) for b in schedule.blocks]


def test_single_task_gets_its_duration() -> None:
    request = PlanRequest(
        horizon_start=z(11, 23, 8),
        horizon_end=z(11, 23, 12),
        tasks=[task("Analysis", 120, z(11, 23, 12))],
    )
    solved(request)


def test_works_around_lecture_when_only_one_way_fits() -> None:
    lecture = Event(id="l", title="Lecture", start=z(11, 23, 9), end=z(11, 23, 11))
    request = PlanRequest(
        horizon_start=z(11, 23, 8),
        horizon_end=z(11, 23, 12),
        tasks=[task("Analysis", 120, z(11, 23, 12))],
    )
    schedule = solved(request, [lecture])
    assert used(schedule) == [
        (z(11, 23, 8), z(11, 23, 9)),
        (z(11, 23, 11), z(11, 23, 12)),
    ]


def test_respects_deadline_and_earliest_start() -> None:
    request = PlanRequest(
        horizon_start=z(11, 23, 8),
        horizon_end=z(11, 23, 12),
        tasks=[
            task("Early", 60, z(11, 23, 9)),
            task("Late", 60, z(11, 23, 12), earliest_start=z(11, 23, 11)),
        ],
    )
    schedule = solved(request)
    assert used(schedule) == [
        (z(11, 23, 8), z(11, 23, 9)),
        (z(11, 23, 11), z(11, 23, 12)),
    ]


def test_two_tasks_share_a_full_window_without_clashing() -> None:
    request = PlanRequest(
        horizon_start=z(11, 23, 8),
        horizon_end=z(11, 23, 10),
        tasks=[task("A", 60, z(11, 23, 10)), task("B", 60, z(11, 23, 10))],
    )
    solved(request)


def test_day_hours_and_blocked_window_on_dst_day() -> None:
    # 29 Mar 2026: clocks jump 02:00 -> 03:00. 9-17 local is still 8 hours.
    request = PlanRequest(
        horizon_start=z(3, 29, 0),
        horizon_end=z(3, 30, 0),
        tasks=[task("Revision", 7 * 60, z(3, 30, 0))],
        day_start=time(9),
        day_end=time(17),
        blocked=[Window(start=z(3, 29, 12), end=z(3, 29, 13))],
    )
    schedule = solved(request)
    assert used(schedule) == [(z(3, 29, 9), z(3, 29, 12)), (z(3, 29, 13), z(3, 29, 17))]


def test_impossible_request_is_infeasible() -> None:
    # Brief example 5: "Fit 20 hours of revision into tomorrow."
    request = PlanRequest(
        horizon_start=z(11, 24, 0),
        horizon_end=z(11, 25, 0),
        tasks=[task("Revision", 20 * 60, z(11, 25, 0))],
        day_start=time(9),
        day_end=time(22),
    )
    result = solve(request, [])
    assert result.status == SolveStatus.INFEASIBLE
    assert result.schedule is None


def test_horizon_shorter_than_one_slot_is_infeasible() -> None:
    request = PlanRequest(
        horizon_start=z(11, 23, 9, 1),
        horizon_end=z(11, 23, 9, 14),
        tasks=[task("Tiny", 15, z(11, 23, 9, 14))],
    )
    assert solve(request, []).status == SolveStatus.INFEASIBLE


# --- block lengths ---


def test_minimum_block_rules_out_short_leftovers() -> None:
    # Free: 8:00-8:30 and 9:00-9:45. 60 min only fits as 15 + 45 or 30 + 30.
    lecture = Event(id="l", title="Lecture", start=z(11, 23, 8, 30), end=z(11, 23, 9))
    request = PlanRequest(
        horizon_start=z(11, 23, 8),
        horizon_end=z(11, 23, 9, 45),
        tasks=[task("Analysis", 60, z(11, 23, 9, 45), min_block_min=30)],
    )
    schedule = solved(request, [lecture])
    assert all(b.end - b.start >= timedelta(minutes=30) for b in schedule.blocks)

    longer = request.model_copy(
        update={"tasks": [task("Analysis", 60, z(11, 23, 9, 45), min_block_min=45)]}
    )
    assert solve(longer, [lecture]).status == SolveStatus.INFEASIBLE


def test_block_cannot_start_too_close_to_horizon_end() -> None:
    # Only 8:00-8:15 and 8:45-9:15 are free; a 30-min block must use the second.
    lecture = Event(
        id="l", title="Lecture", start=z(11, 23, 8, 15), end=z(11, 23, 8, 45)
    )
    request = PlanRequest(
        horizon_start=z(11, 23, 8),
        horizon_end=z(11, 23, 9, 15),
        tasks=[task("Analysis", 30, z(11, 23, 9, 15))],
    )
    assert used(solved(request, [lecture])) == [(z(11, 23, 8, 45), z(11, 23, 9, 15))]


def test_maximum_block_splits_long_task() -> None:
    request = PlanRequest(
        horizon_start=z(11, 23, 8),
        horizon_end=z(11, 23, 12),
        tasks=[task("Analysis", 180, z(11, 23, 12), max_block_min=60)],
    )
    schedule = solved(request)
    assert len(schedule.blocks) == 3  # three 1h blocks, separated by breaks


# --- daily cap ---


def test_daily_cap_spreads_work_over_days() -> None:
    request = PlanRequest(
        horizon_start=z(11, 23, 0),
        horizon_end=z(11, 25, 0),
        tasks=[task("Analysis", 240, z(11, 25, 0))],
        max_work_min_per_day=120,
    )
    schedule = solved(request)
    assert {b.start.astimezone(ZURICH).day for b in schedule.blocks} == {23, 24}


def test_daily_cap_too_low_is_infeasible() -> None:
    request = PlanRequest(
        horizon_start=z(11, 23, 0),
        horizon_end=z(11, 25, 0),
        tasks=[task("Analysis", 300, z(11, 25, 0))],
        max_work_min_per_day=120,
    )
    assert solve(request, []).status == SolveStatus.INFEASIBLE


# --- objective ---


def test_prefers_one_block_over_several() -> None:
    request = PlanRequest(
        horizon_start=z(11, 23, 8),
        horizon_end=z(11, 23, 12),
        tasks=[task("Analysis", 60, z(11, 23, 12))],
    )
    assert len(solved(request).blocks) == 1


def test_avoids_late_evening_when_possible() -> None:
    request = PlanRequest(
        horizon_start=z(11, 23, 18),
        horizon_end=z(11, 23, 23),
        tasks=[task("Analysis", 120, z(11, 23, 23))],
    )
    assert used(solved(request)) == [(z(11, 23, 18), z(11, 23, 20))]


# --- the checker agrees on many random calendars ---


@pytest.mark.parametrize("seed", range(25))
def test_random_requests_pass_the_checker(seed: int) -> None:
    rng = random.Random(seed)
    events = []
    for n in range(rng.randint(0, 6)):
        day, hour = rng.randint(23, 24), rng.randint(8, 19)
        start = z(11, day, hour, rng.choice([0, 10, 30, 45]))
        events.append(
            Event(
                id=f"e{n}",
                title="Busy",
                start=start,
                end=start + timedelta(minutes=rng.choice([30, 50, 90])),
            )
        )
    tasks = [
        task(
            f"T{k}",
            15 * rng.randint(1, 12),
            z(11, rng.randint(23, 24), 23),
            min_block_min=rng.choice([15, 30, 45]),
            max_block_min=rng.choice([None, 60, 90]),
        )
        for k in range(rng.randint(1, 3))
    ]
    request = PlanRequest(
        horizon_start=z(11, 23, 7, 5),
        horizon_end=z(11, 25, 0),
        tasks=tasks,
        day_start=time(8),
        day_end=time(22),
        max_work_min_per_day=rng.choice([None, 180, 240]),
    )
    result = solve(request, events)
    if result.status == SolveStatus.INFEASIBLE:
        return  # the checker can only judge schedules that exist
    assert result.status == SolveStatus.OPTIMAL
    assert result.schedule is not None
    assert check(request, events, result.schedule) == []
