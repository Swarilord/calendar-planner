"""Tests for the CP-SAT solver. The independent checker is the referee."""

from collections.abc import Sequence
from datetime import datetime, time
from zoneinfo import ZoneInfo

from planner.calendar.models import Event
from planner.checker.check import check
from planner.parser.schemas import PlanRequest, Task, Window
from planner.schedule import Schedule
from planner.solver.model import SolveStatus, solve

ZURICH = ZoneInfo("Europe/Zurich")


def z(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=ZURICH)


def task(name: str, minutes: int, deadline: datetime, **extra: object) -> Task:
    # min_block_min=15 until block-length rules are added to the solver
    fields = {"name": name, "duration_min": minutes, "deadline": deadline}
    return Task.model_validate({"min_block_min": 15, **fields, **extra})


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
