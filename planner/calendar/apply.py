"""Write a confirmed plan into a calendar, safely and idempotently.

Idempotent: applying the same schedule twice gives the same calendar as applying
it once. A block counts as "already there" if an event this app created has the
same title, start and end, so a double click, a retry after a network error or
a crash halfway through never creates duplicates; the next apply just adds the
blocks that are still missing.

Safe: before writing, the calendar is read again. If any block now clashes with
another event (one added after the preview), nothing is written and the clashes
are returned, so the agent can propose a new plan.
"""

from dataclasses import dataclass, field

from planner.calendar.backend import CalendarBackend
from planner.calendar.models import Event, NewEvent
from planner.common import overlaps
from planner.schedule import Schedule, ScheduledBlock


@dataclass(frozen=True)
class ApplyResult:
    created: list[Event] = field(default_factory=list)
    already_there: int = 0  # blocks skipped because they already exist
    conflicts: list[Event] = field(default_factory=list)  # nothing written if any

    @property
    def ok(self) -> bool:
        return not self.conflicts


def apply_plan(
    calendar: CalendarBackend, plan_id: str, schedule: Schedule
) -> ApplyResult:
    """Create the schedule's blocks that are not in the calendar yet."""
    if not schedule.blocks:
        return ApplyResult()
    start = min(block.start for block in schedule.blocks)
    end = max(block.end for block in schedule.blocks)
    existing = calendar.list_events(start, end)

    missing = [b for b in schedule.blocks if not any(_same(b, e) for e in existing)]
    # Any event that is not one of our blocks is a commitment we must not overlap.
    others = [e for e in existing if not any(_same(b, e) for b in schedule.blocks)]
    conflicts = [
        e
        for e in others
        if any(overlaps(b.start, b.end, e.start, e.end) for b in missing)
    ]
    if conflicts:
        return ApplyResult(conflicts=conflicts)

    created = [
        calendar.create_event(
            NewEvent(title=b.task_name, start=b.start, end=b.end, plan_id=plan_id)
        )
        for b in missing
    ]
    return ApplyResult(
        created=created, already_there=len(schedule.blocks) - len(missing)
    )


def _same(block: ScheduledBlock, event: Event) -> bool:
    """Is this event the block, written by us earlier?"""
    return (
        event.created_by_planner
        and event.title == block.task_name
        and event.start == block.start
        and event.end == block.end
    )
