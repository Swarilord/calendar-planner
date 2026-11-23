"""The CP-SAT model: colour the grid's slots so that every rule holds.

x[i][t] = 1 means task i uses slot t. The solver chooses all x values at once;
afterwards each run of consecutive used slots becomes one ScheduledBlock.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from ortools.sat.python import cp_model

from planner.calendar.models import Event
from planner.parser.schemas import GRANULARITY_MIN, PlanRequest
from planner.schedule import Schedule, ScheduledBlock
from planner.solver.grid import Grid, build_grid

TIME_LIMIT_S = 10.0


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
