"""The slot grid: real time cut into 15-minute squares for the solver.

CP-SAT only understands whole numbers, so before building the model we work
out once, for every slot, when it starts, which local day it belongs to and
why it might be off limits. Each reason is kept separate, so the infeasibility
explanation can later switch one group of rules on or off at a time.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from planner.calendar.models import Event
from planner.common import overlaps
from planner.parser.schemas import GRANULARITY_MIN, PlanRequest

SLOT = timedelta(minutes=GRANULARITY_MIN)


@dataclass(frozen=True)
class Grid:
    """Slot t covers [starts[t], starts[t] + SLOT).

    Every list has exactly one entry per slot.
    """

    starts: list[datetime]  # UTC
    local_days: list[date]  # the slot's date in request.timezone
    busy: list[bool]  # an existing event overlaps the slot
    outside_day_hours: list[bool]
    in_blocked_window: list[bool]

    @property
    def n_slots(self) -> int:
        return len(self.starts)

    def end(self, t: int) -> datetime:
        return self.starts[t] + SLOT

    def first_slot_from(self, moment: datetime) -> int:
        """Index of the first slot starting at or after `moment`."""
        return bisect_left(self.starts, moment)

    def slots_ending_by(self, moment: datetime) -> int:
        """Number of slots that end at or before `moment` (the brief's D_i)."""
        return bisect_right(self.starts, moment - SLOT)


def build_grid(request: PlanRequest, events: Sequence[Event]) -> Grid:
    tz = ZoneInfo(request.timezone)
    starts = []
    start = _round_up(request.horizon_start)
    while start + SLOT <= request.horizon_end:
        starts.append(start)
        start += SLOT

    return Grid(
        starts=starts,
        local_days=[s.astimezone(tz).date() for s in starts],
        busy=[
            any(overlaps(s, s + SLOT, e.start, e.end) for e in events) for s in starts
        ],
        outside_day_hours=[not _in_day_hours(s, request, tz) for s in starts],
        in_blocked_window=[
            any(overlaps(s, s + SLOT, w.start, w.end) for w in request.blocked)
            for s in starts
        ],
    )


def _round_up(moment: datetime) -> datetime:
    """Next quarter hour at or after `moment` (UTC; Zurich offsets are whole hours)."""
    floor = moment.replace(
        minute=moment.minute - moment.minute % GRANULARITY_MIN, second=0, microsecond=0
    )
    return floor if floor == moment else floor + SLOT


def _in_day_hours(slot_start: datetime, request: PlanRequest, tz: ZoneInfo) -> bool:
    """Compare the slot's local wall-clock times with day_start/day_end.

    A slot is only 15 minutes, so a plain clock comparison is enough. This is
    deliberately a different method from the checker's, which builds a
    window per day: two methods agreeing is stronger evidence than one.
    """
    local_start = slot_start.astimezone(tz)
    local_end = (slot_start + SLOT).astimezone(tz)
    if request.day_start is not None and local_start.time() < request.day_start:
        return False
    if request.day_end is not None and (
        local_end.date() != local_start.date() or local_end.time() > request.day_end
    ):
        return False
    return True
