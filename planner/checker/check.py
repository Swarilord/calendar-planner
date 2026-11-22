"""Independent schedule checker.

Given a request, the existing calendar events and a proposed schedule, list
every rule the schedule breaks. It knows nothing about how the solver works:
it only looks at the result, using plain Python.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from itertools import combinations
from zoneinfo import ZoneInfo

from planner.calendar.models import Event
from planner.common import Schema, overlaps
from planner.parser.schemas import PlanRequest
from planner.schedule import Schedule, ScheduledBlock


class ViolationKind(StrEnum):
    UNKNOWN_TASK = "unknown_task"
    CLASHES_WITH_EVENT = "clashes_with_event"
    CLASHES_WITH_BLOCK = "clashes_with_block"
    AFTER_DEADLINE = "after_deadline"
    OUTSIDE_HORIZON = "outside_horizon"
    BEFORE_EARLIEST_START = "before_earliest_start"
    OUTSIDE_DAY_HOURS = "outside_day_hours"
    IN_BLOCKED_WINDOW = "in_blocked_window"
    BLOCK_TOO_SHORT = "block_too_short"
    BLOCK_TOO_LONG = "block_too_long"
    WRONG_TOTAL = "wrong_total"
    DAILY_CAP_EXCEEDED = "daily_cap_exceeded"


class Violation(Schema):
    """One broken rule, with a human-readable explanation."""

    kind: ViolationKind
    task_name: str | None
    message: str


def check(
    request: PlanRequest, events: Sequence[Event], schedule: Schedule
) -> list[Violation]:
    """Return every rule the schedule breaks. An empty list means it is valid."""
    tasks = {task.name: task for task in request.tasks}
    violations: list[Violation] = []

    for block in schedule.blocks:
        task = tasks.get(block.task_name)
        if task is None:
            violations.append(
                _violation(ViolationKind.UNKNOWN_TASK, block, "is not in the request")
            )
            continue

        if block.start < request.horizon_start or block.end > request.horizon_end:
            violations.append(
                _violation(
                    ViolationKind.OUTSIDE_HORIZON, block, "is outside the horizon"
                )
            )

        if block.end > task.deadline:
            violations.append(
                _violation(
                    ViolationKind.AFTER_DEADLINE, block, "ends after the deadline"
                )
            )

        if task.earliest_start is not None and block.start < task.earliest_start:
            violations.append(
                _violation(
                    ViolationKind.BEFORE_EARLIEST_START,
                    block,
                    "starts before the task's earliest start",
                )
            )

        if not _within_day_hours(block, request):
            violations.append(
                _violation(
                    ViolationKind.OUTSIDE_DAY_HOURS,
                    block,
                    "is outside the allowed hours of the day",
                )
            )

        minutes = _minutes(block.start, block.end)
        if minutes < task.shortest_block_min:
            violations.append(
                _violation(
                    ViolationKind.BLOCK_TOO_SHORT,
                    block,
                    f"is {minutes} min, shorter than {task.shortest_block_min} min",
                )
            )
        if task.max_block_min is not None and minutes > task.max_block_min:
            violations.append(
                _violation(
                    ViolationKind.BLOCK_TOO_LONG,
                    block,
                    f"is {minutes} min, longer than {task.max_block_min} min",
                )
            )

        for window in request.blocked:
            if overlaps(block.start, block.end, window.start, window.end):
                violations.append(
                    _violation(
                        ViolationKind.IN_BLOCKED_WINDOW,
                        block,
                        "falls in a time I asked to keep free",
                    )
                )

        for event in events:
            if overlaps(block.start, block.end, event.start, event.end):
                violations.append(
                    _violation(
                        ViolationKind.CLASHES_WITH_EVENT,
                        block,
                        f"clashes with event {event.title!r}",
                    )
                )

    for a, b in combinations(schedule.blocks, 2):
        if overlaps(a.start, a.end, b.start, b.end):
            violations.append(
                _violation(
                    ViolationKind.CLASHES_WITH_BLOCK,
                    a,
                    f"clashes with another block of {b.task_name!r}",
                )
            )

    violations += _total_violations(request, schedule)
    violations += _daily_cap_violations(request, schedule)
    return violations


def _minutes(start: datetime, end: datetime) -> int:
    """Real elapsed minutes. UTC subtraction is correct across DST switches."""
    return int((end - start).total_seconds() // 60)


def _total_violations(request: PlanRequest, schedule: Schedule) -> list[Violation]:
    """Each task's blocks must add up to exactly its duration."""
    violations = []
    for task in request.tasks:
        scheduled = sum(
            _minutes(b.start, b.end)
            for b in schedule.blocks
            if b.task_name == task.name
        )
        if scheduled != task.duration_min:
            violations.append(
                Violation(
                    kind=ViolationKind.WRONG_TOTAL,
                    task_name=task.name,
                    message=(
                        f"{task.name!r} has {scheduled} of "
                        f"{task.duration_min} minutes scheduled."
                    ),
                )
            )
    return violations


def _daily_cap_violations(request: PlanRequest, schedule: Schedule) -> list[Violation]:
    """Work per local day must not exceed max_work_min_per_day."""
    if request.max_work_min_per_day is None:
        return []
    tz = ZoneInfo(request.timezone)
    per_day: dict[date, int] = defaultdict(int)
    for block in schedule.blocks:
        # Split blocks that cross local midnight between the two days.
        start = block.start
        while start < block.end:
            day = start.astimezone(tz).date()
            next_midnight = datetime.combine(
                day + timedelta(days=1), time(0, 0), tzinfo=tz
            )
            piece_end = min(block.end, next_midnight)
            per_day[day] += _minutes(start, piece_end)
            start = piece_end
    cap = request.max_work_min_per_day
    return [
        Violation(
            kind=ViolationKind.DAILY_CAP_EXCEEDED,
            task_name=None,
            message=f"{day:%a %d %b} has {total} minutes of work, more than {cap}.",
        )
        for day, total in sorted(per_day.items())
        if total > cap
    ]


def _within_day_hours(block: ScheduledBlock, request: PlanRequest) -> bool:
    """True if the block fits inside one local day's allowed hours.

    day_start/day_end are wall-clock times in request.timezone, so the allowed
    window is built separately for the block's local date. zoneinfo applies
    that date's UTC offset, which handles the daylight-saving switches.
    """
    if request.day_start is None and request.day_end is None:
        return True
    tz = ZoneInfo(request.timezone)
    day = block.start.astimezone(tz).date()
    window_start = datetime.combine(day, request.day_start or time(0, 0), tzinfo=tz)
    if request.day_end is None:
        window_end = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=tz)
    else:
        window_end = datetime.combine(day, request.day_end, tzinfo=tz)
    return window_start <= block.start and block.end <= window_end


def _violation(kind: ViolationKind, block: ScheduledBlock, problem: str) -> Violation:
    when = f"{block.start:%a %d %b %H:%M}-{block.end:%H:%M} UTC"
    return Violation(
        kind=kind,
        task_name=block.task_name,
        message=f"Block for {block.task_name!r} ({when}) {problem}.",
    )
