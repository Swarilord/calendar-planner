"""The CP-SAT model: colour the grid's slots so that every rule holds.

x[i][t] = 1 means task i uses slot t; s[i][t] = 1 means a block of task i
starts at slot t. The solver chooses all values at once; afterwards each run of
consecutive used slots becomes one ScheduledBlock.

Rules the user could relax (a deadline, the day hours, a blocked window, ...)
each sit behind a switch. If no plan exists, CP-SAT reports which switches
together make it impossible, and that becomes the explanation.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
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


class Rule(StrEnum):
    """Groups of rules that can be named in an explanation."""

    DEADLINE = "deadline"
    EARLIEST_START = "earliest_start"
    DAY_HOURS = "day_hours"
    BLOCKED_WINDOW = "blocked_window"
    BLOCK_LENGTH = "block_length"
    DAILY_CAP = "daily_cap"


@dataclass(frozen=True)
class Conflict:
    """One rule that is part of the reason a request is impossible."""

    rule: Rule
    task_name: str | None
    description: str


@dataclass(frozen=True)
class SolveResult:
    status: SolveStatus
    schedule: Schedule | None = None  # only for OPTIMAL and FEASIBLE
    # Only for INFEASIBLE: rules that cannot all hold together. Without any one
    # of them, a plan exists. It is one reason, not necessarily the only one.
    # Empty means: impossible even without these rules (no free time at all).
    conflicts: list[Conflict] = field(default_factory=list)


@dataclass(frozen=True)
class _Switch:
    literal: cp_model.IntVar
    conflict: Conflict


@dataclass(frozen=True)
class _Built:
    model: cp_model.CpModel
    x: list[list[cp_model.IntVar]]
    switches: dict[int, _Switch]  # keyed by the literal's variable index


def solve(
    request: PlanRequest,
    events: Sequence[Event],
    time_limit_s: float = TIME_LIMIT_S,
) -> SolveResult:
    grid = build_grid(request, events)
    built = _build(request, grid, explain=False)
    solver = _solver(time_limit_s)
    status = solver.solve(built.model)

    if status == cp_model.INFEASIBLE:
        # Second pass, only for impossible requests: switches as assumptions.
        explaining = _build(request, grid, explain=True)
        solver = _solver(time_limit_s)
        solver.solve(explaining.model)
        # The core lists variable indices of switches, not list positions.
        core = [
            explaining.switches[index]
            for index in solver.sufficient_assumptions_for_infeasibility()
        ]
        conflicts = _shrink(explaining.model, core, time_limit_s)
        return SolveResult(SolveStatus.INFEASIBLE, conflicts=conflicts)
    if status == cp_model.UNKNOWN:
        return SolveResult(SolveStatus.TIMED_OUT)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # MODEL_INVALID means a bug in this file, not a bad request.
        raise RuntimeError(f"CP-SAT returned {solver.status_name(status)}")

    blocks = [
        block
        for i, task in enumerate(request.tasks)
        for block in _blocks(
            task.name, [solver.boolean_value(v) for v in built.x[i]], grid
        )
    ]
    blocks.sort(key=lambda b: b.start)
    found = SolveStatus.OPTIMAL if status == cp_model.OPTIMAL else SolveStatus.FEASIBLE
    return SolveResult(found, Schedule(blocks=blocks))


def _build(request: PlanRequest, grid: Grid, *, explain: bool) -> _Built:
    """Build the model. explain=False fixes every switch on (fast: presolve can
    simplify with it); explain=True makes them assumptions CP-SAT can report."""
    tz = ZoneInfo(request.timezone)
    slots = range(grid.n_slots)
    tasks = request.tasks
    model = cp_model.CpModel()
    switches: list[_Switch] = []

    def switch(rule: Rule, task_name: str | None, description: str) -> cp_model.IntVar:
        """A new on/off switch for one group of rules."""
        literal = model.new_bool_var(f"switch[{rule},{task_name}]")
        switches.append(_Switch(literal, Conflict(rule, task_name, description)))
        return literal

    def forbid(
        cells: list[cp_model.IntVar],
        rule: Rule,
        task_name: str | None,
        description: str,
    ) -> None:
        """These cells stay empty while the group's switch is on."""
        if cells:  # a group that forbids nothing needs no switch
            literal = switch(rule, task_name, description)
            model.add(sum(cells) == 0).only_enforce_if(literal)

    x = [[model.new_bool_var(f"x[{i},{t}]") for t in slots] for i in range(len(tasks))]

    for i, task in enumerate(tasks):
        # Rule 1 (always on): the task gets exactly its duration.
        model.add(sum(x[i]) == task.duration_min // GRANULARITY_MIN)

        # Rule 2, split by reason: deadline, earliest start ...
        late = grid.slots_ending_by(task.deadline)
        forbid(
            [x[i][t] for t in range(late, grid.n_slots)],
            Rule.DEADLINE,
            task.name,
            f"{task.name!r} is due {_local(task.deadline, tz)}",
        )
        if task.earliest_start is not None:
            early = grid.first_slot_from(task.earliest_start)
            forbid(
                [x[i][t] for t in range(early)],
                Rule.EARLIEST_START,
                task.name,
                f"{task.name!r} cannot start before {_local(task.earliest_start, tz)}",
            )

    # ... day hours, and each blocked window on its own.
    day_start = f"{request.day_start or time(0, 0):%H:%M}"
    day_end = "midnight" if request.day_end is None else f"{request.day_end:%H:%M}"
    outside = [t for t in slots if grid.outside_day_hours[t]]
    forbid(
        [row[t] for row in x for t in outside],
        Rule.DAY_HOURS,
        None,
        f"work only between {day_start} and {day_end}",
    )
    for window, window_slots in zip(request.blocked, grid.blocked_slots, strict=True):
        forbid(
            [row[t] for row in x for t in window_slots],
            Rule.BLOCKED_WINDOW,
            None,
            f"keep {_local(window.start, tz)}-{window.end.astimezone(tz):%H:%M} free",
        )

    # Rule 3 (always on): at most one task per slot, none on a busy slot.
    for t in slots:
        capacity = 0 if grid.busy[t] else 1
        model.add(sum(row[t] for row in x) <= capacity)

    s = [[model.new_bool_var(f"s[{i},{t}]") for t in slots] for i in range(len(tasks))]
    for i, task in enumerate(tasks):
        # Rule 4 (always on): used now but not just before = a block starts.
        # Only ">=": the objective keeps s at 0 wherever it is not forced.
        for t in slots:
            previous = x[i][t - 1] if t > 0 else 0
            model.add(s[i][t] >= x[i][t] - previous)

        shortest = task.shortest_block_min // GRANULARITY_MIN
        if shortest == 1 and task.max_block_min is None:
            continue  # no block-length rule for this task
        description = (
            f"{task.name!r} in blocks of at least {task.shortest_block_min} min"
        )
        if task.max_block_min is not None:
            description += f" and at most {task.max_block_min} min"
        lengths_on = switch(Rule.BLOCK_LENGTH, task.name, description)

        # Rule 5: a block that starts here lasts at least `shortest` slots.
        for t in slots:
            if t + shortest > grid.n_slots:  # it would run past the horizon
                model.add(s[i][t] == 0).only_enforce_if(lengths_on)
            else:
                for j in range(shortest):
                    model.add(x[i][t + j] >= s[i][t]).only_enforce_if(lengths_on)

        # Rule 7: any longest + 1 slots in a row contain an unused slot.
        if task.max_block_min is not None:
            longest = task.max_block_min // GRANULARITY_MIN
            for t in range(grid.n_slots - longest):
                model.add(sum(x[i][t : t + longest + 1]) <= longest).only_enforce_if(
                    lengths_on
                )
            # Redundant rule: true anyway, but tells the solver directly that
            # it needs at least ceil(duration / longest) blocks. Without it,
            # proving a plan optimal can take longer than the time limit.
            needed = -(-task.duration_min // task.max_block_min)  # ceil
            model.add(sum(s[i]) >= needed).only_enforce_if(lengths_on)

    # Rule 6: daily cap per local day, rounded down to whole slots (safe side).
    if request.max_work_min_per_day is not None:
        cap_on = switch(
            Rule.DAILY_CAP,
            None,
            f"at most {request.max_work_min_per_day} min of work per day",
        )
        cap = request.max_work_min_per_day // GRANULARITY_MIN
        slots_by_day: dict[date, list[int]] = defaultdict(list)
        for t in slots:
            slots_by_day[grid.local_days[t]].append(t)
        for day_slots in slots_by_day.values():
            model.add(
                sum(row[t] for row in x for t in day_slots) <= cap
            ).only_enforce_if(cap_on)

    # Objective: few blocks first, then few unpleasant (early/late) slots.
    unpleasant = [t for t in slots if _is_unpleasant(grid.starts[t], tz)]
    model.minimize(
        BLOCK_COST * sum(sum(row) for row in s)
        + UNPLEASANT_SLOT_COST * sum(row[t] for row in x for t in unpleasant)
    )

    literals = [sw.literal for sw in switches]
    if explain:
        # Assume every switch is on; if impossible, CP-SAT names a set of them.
        model.add_assumptions(literals)
    else:
        for literal in literals:
            model.add(literal == 1)
    return _Built(model, x, {sw.literal.index: sw for sw in switches})


def _shrink(
    model: cp_model.CpModel, core: list[_Switch], time_limit_s: float
) -> list[Conflict]:
    """Drop every switch the request stays impossible without.

    CP-SAT's set is sufficient (together impossible) but may contain extras.
    Try leaving each one out; keep it only if the request then becomes possible.
    """
    needed = list(core)
    for candidate in core:
        trial = [sw for sw in needed if sw is not candidate]
        model.clear_assumptions()
        model.add_assumptions([sw.literal for sw in trial])
        solver = _solver(time_limit_s)
        solver.parameters.stop_after_first_solution = True  # any plan will do
        if solver.solve(model) == cp_model.INFEASIBLE:
            needed = trial
    return [sw.conflict for sw in needed]


def _solver(time_limit_s: float) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    return solver


def _local(moment: datetime, tz: ZoneInfo) -> str:
    return f"{moment.astimezone(tz):%a %d %b %H:%M}"


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
