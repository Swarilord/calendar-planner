"""Independent schedule checker.

Given a request, the existing calendar events and a proposed schedule, list
every rule the schedule breaks. It knows nothing about how the solver works:
it only looks at the result, using plain Python.
"""

from collections.abc import Sequence
from enum import StrEnum
from itertools import combinations

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

    return violations


def _violation(kind: ViolationKind, block: ScheduledBlock, problem: str) -> Violation:
    when = f"{block.start:%a %d %b %H:%M}-{block.end:%H:%M} UTC"
    return Violation(
        kind=kind,
        task_name=block.task_name,
        message=f"Block for {block.task_name!r} ({when}) {problem}.",
    )
