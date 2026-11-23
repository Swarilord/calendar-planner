"""The CP-SAT model: colour the grid's slots so that every rule holds.

x[i][t] = 1 means task i uses slot t; s[i][t] = 1 means a block of task i
starts at slot t. The solver chooses all values at once; afterwards each run of
consecutive used slots becomes one ScheduledBlock.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo

from ortools.sat.python import cp_model

from planner.calendar.models import Event
from planner.parser.schemas import GRANULARITY_MIN, PlanRequest
from planner.schedule import Schedule, ScheduledBlock
from planner.solver.grid import Grid, build_grid

TIME_LIMIT_S = 10.0

# Objective weights: one extra block costs as much as an hour (4 slots) of
# unpleasant time. Integers, because CP-SAT objectives are whole numbers.
BLOCK_COST = 4
UNPLEASANT_SLOT_COST = 1
PLEASANT_FROM = time(8, 0)  # local time; slots outside [8:00, 20:00) cost extra
PLEASANT_UNTIL = time(20, 0)


class SolveStatus(StrEnum):
    OPTIMAL = "optimal"  # best plan, proven best
    FEASIBLE = "feasible"  # valid plan; time ran out before proving it best
    INFEASIBLE = "infeasible"  # proven: no valid plan exists
    TIMED_OUT = "timed_out"  # no plan found and no proof that none exists


@dataclass(frozen=True)
class SolveResult:
    status: SolveStatus
    schedule: Schedule | None  # only set for OPTIMAL and FEASIBLE


def solve(
    request: PlanRequest,
    events: Sequence[Event],
    time_limit_s: float = TIME_LIMIT_S,
) -> SolveResult:
    grid = build_grid(request, events)
    slots = range(grid.n_slots)
    model = cp_model.CpModel()
    x = [
        [model.new_bool_var(f"x[{i},{t}]") for t in slots]
        for i in range(len(request.tasks))
    ]

    for i, task in enumerate(request.tasks):
        # Rule 1: the task gets exactly its duration.
        model.add(sum(x[i]) == task.duration_min // GRANULARITY_MIN)

        # Rule 2: slots this task may not use stay empty.
        first = (
            0
            if task.earliest_start is None
            else grid.first_slot_from(task.earliest_start)
        )
        deadline = grid.slots_ending_by(task.deadline)
        for t in slots:
            if (
                t < first
                or t >= deadline
                or grid.outside_day_hours[t]
                or grid.in_blocked_window[t]
            ):
                model.add(x[i][t] == 0)

    # Rule 3: at most one task per slot, and none on a busy slot.
    for t in slots:
        capacity = 0 if grid.busy[t] else 1
        model.add(sum(x[i][t] for i in range(len(request.tasks))) <= capacity)

    # s[i][t] = 1 if a block of task i starts at slot t.
    s = [
        [model.new_bool_var(f"s[{i},{t}]") for t in slots]
        for i in range(len(request.tasks))
    ]
    for i, task in enumerate(request.tasks):
        shortest = task.shortest_block_min // GRANULARITY_MIN
        for t in slots:
            # Rule 4: used now but not just before means a block starts here.
            # Only ">=": the objective keeps s at 0 wherever it is not forced.
            previous = x[i][t - 1] if t > 0 else 0
            model.add(s[i][t] >= x[i][t] - previous)

            # Rule 5: a block that starts here lasts at least `shortest` slots.
            if t + shortest > grid.n_slots:
                model.add(s[i][t] == 0)  # it would run past the horizon
            else:
                for j in range(shortest):
                    model.add(x[i][t + j] >= s[i][t])

        # Rule 7: no block longer than max_block: any longest + 1 slots in a row
        # contain at least one unused slot.
        if task.max_block_min is not None:
            longest = task.max_block_min // GRANULARITY_MIN
            for t in range(grid.n_slots - longest):
                model.add(sum(x[i][t : t + longest + 1]) <= longest)
            # Redundant rule: true anyway, but tells the solver directly that
            # it needs at least ceil(duration / longest) blocks. Without it,
            # proving a plan optimal can take longer than the time limit.
            needed = -(-task.duration_min // task.max_block_min)  # ceil
            model.add(sum(s[i]) >= needed)

    # Rule 6: daily cap, per local day. Rounded down to whole slots (safe side).
    if request.max_work_min_per_day is not None:
        cap = request.max_work_min_per_day // GRANULARITY_MIN
        slots_by_day: dict[date, list[int]] = defaultdict(list)
        for t in slots:
            slots_by_day[grid.local_days[t]].append(t)
        for day_slots in slots_by_day.values():
            model.add(sum(row[t] for row in x for t in day_slots) <= cap)

    # Objective: few blocks first, then few unpleasant (early/late) slots.
    tz = ZoneInfo(request.timezone)
    unpleasant = [t for t in slots if _is_unpleasant(grid.starts[t], tz)]
    model.minimize(
        BLOCK_COST * sum(sum(row) for row in s)
        + UNPLEASANT_SLOT_COST * sum(row[t] for row in x for t in unpleasant)
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.solve(model)

    if status == cp_model.INFEASIBLE:
        return SolveResult(SolveStatus.INFEASIBLE, None)
    if status == cp_model.UNKNOWN:
        return SolveResult(SolveStatus.TIMED_OUT, None)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # MODEL_INVALID means a bug in this file, not a bad request.
        raise RuntimeError(f"CP-SAT returned {solver.status_name(status)}")

    blocks = [
        block
        for i, task in enumerate(request.tasks)
        for block in _blocks(task.name, [solver.boolean_value(v) for v in x[i]], grid)
    ]
    blocks.sort(key=lambda b: b.start)
    found = SolveStatus.OPTIMAL if status == cp_model.OPTIMAL else SolveStatus.FEASIBLE
    return SolveResult(found, Schedule(blocks=blocks))


def _is_unpleasant(slot_start: datetime, tz: ZoneInfo) -> bool:
    clock = slot_start.astimezone(tz).time()
    return not (PLEASANT_FROM <= clock < PLEASANT_UNTIL)


def _blocks(task_name: str, used: list[bool], grid: Grid) -> list[ScheduledBlock]:
    """Turn each run of consecutive used slots into one block."""
    blocks = []
    t = 0
    while t < len(used):
        if not used[t]:
            t += 1
            continue
        first = t
        while t < len(used) and used[t]:
            t += 1
        blocks.append(
            ScheduledBlock(
                task_name=task_name, start=grid.starts[first], end=grid.end(t - 1)
            )
        )
    return blocks
