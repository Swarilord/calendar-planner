# Decisions

One entry per decision: what I chose, the alternatives, and why (in my own words).

## Phase 0: repo skeleton

### Python 3.13
- **Chose:** Python 3.13.
- **Alternatives:** 3.14 (newest), 3.12 (older).
- **Why:**

### Flat layout
- **Chose:** the package lives in `planner/` at the top level.
- **Alternatives:** `src/planner/` (src layout).
- **Why:**

### mypy in strict mode
- **Chose:** `strict = true`.
- **Alternatives:** default mypy, or no type checker.
- **Why:**

### Repo outside iCloud
- **Chose:** `~/code/calendar-planner`.
- **Alternatives:** keep it in `~/Documents` (synced by iCloud Drive).
- **Why:**

### pre-commit hooks call `uv run`
- **Chose:** local hooks (`language: system`, `entry: uv run ...`).
- **Alternatives:** pre-commit's own isolated copies of ruff and mypy.
- **Why:**

### pre-commit and CI
- **Chose:** both.
- **Alternatives:** only pre-commit, or only CI.
- **Why:**

## Phase 1: hello agent

### Hello agent in `experiments/`
- **Chose:** `experiments/hello_agent/`, kept in the repo.
- **Alternatives:** `planner/agent/`, or delete it after Phase 1.
- **Why:**

### Exact model name
- **Chose:** `gemini-3.6-flash`.
- **Alternatives:** the moving alias `gemini-flash-latest`.
- **Why:**

### Tools return a dict
- **Chose:** a dict with labelled fields (`status`, `utc`, `zurich`, `weekday`, ...).
- **Alternatives:** a plain string like `"2026-11-20 21:43"`.
- **Why:**

### gitleaks
- **Chose:** gitleaks as a pre-commit hook.
- **Alternatives:** only `.gitignore` and `detect-private-key`.
- **Why:**

## Phase 2: schemas and calendar backends

### Pydantic as a direct dependency
- **Chose:** `pydantic` listed in our own `pyproject.toml`.
- **Alternatives:** rely on the copy that ADK already installs.
- **Why:**

### Times: timezone required, stored in UTC
- **Chose:** reject naive datetimes; convert every time to UTC when an object is created.
- **Alternatives:** accept naive times and assume Zurich; store Zurich local time.
- **Why:**

### Immutable schemas (`frozen=True`)
- **Chose:** objects cannot be changed after creation; changes make a new object.
- **Alternatives:** normal mutable objects (Pydantic's default).
- **Why:**

### Unknown fields are an error (`extra="forbid"`)
- **Chose:** reject any field the schema doesn't define.
- **Alternatives:** silently ignore unknown fields (Pydantic's default).
- **Why:**

### Ownership as explicit fields
- **Chose:** `created_by_planner: bool` and `plan_id` on `Event`.
- **Alternatives:** a general `tags: dict[str, str]`, mirroring Google's extended properties.
- **Why:**

### Pydantic mypy plugin
- **Chose:** `plugins = ["pydantic.mypy"]`.
- **Alternatives:** plain mypy, which doesn't know Pydantic rules such as `frozen`.
- **Why:**

### Interface as a `Protocol`
- **Chose:** `CalendarBackend(Protocol)`: a calendar fits if it has the right methods (structural typing), checked by mypy.
- **Alternatives:** an abstract base class (ABC) that every calendar must inherit from.
- **Why:**

### Named calendar errors
- **Chose:** `EventNotFoundError` and `NotOwnedError` (both subclasses of `CalendarError`).
- **Alternatives:** return `None`/`False`; raise generic `KeyError`/`ValueError`.
- **Why:**

### Half-open time ranges `[start, end)`
- **Chose:** an event ending exactly when a range starts does not overlap it.
- **Alternatives:** closed ranges, where touching counts as overlapping.
- **Why:**

### Deterministic ids in FakeCalendar
- **Chose:** `fake-1`, `fake-2`, ...
- **Alternatives:** random ids (`uuid4`).
- **Why:**

### Updates rebuild the event
- **Chose:** `Event.model_validate(old fields | changes)`, so every check runs again.
- **Alternatives:** `old.model_copy(update=...)`, which copies without validating.
- **Why:**

### Shared `planner/common.py`
- **Chose:** one module with `Schema` (frozen, forbid) and `UtcDatetime`, imported by calendar and parser.
- **Alternatives:** copy them into each package; let parser import from `calendar.models`.
- **Why:**

### What the schema rejects vs. what the solver handles
- **Chose:** the schema rejects what is nonsense on any calendar (negative duration, backwards horizon, unknown timezone); requests that are only impossible on my calendar go to the solver.
- **Alternatives:** reject impossible requests in the schema too (e.g. more work than hours in the horizon).
- **Why:**

### Times of day stay local
- **Chose:** `day_start`/`day_end` are plain `time` values, read in `PlanRequest.timezone`.
- **Alternatives:** convert them to UTC like datetimes.
- **Why:**

### Timezone stored as a checked name
- **Chose:** `timezone: str`, validated by trying `ZoneInfo(name)`.
- **Alternatives:** store a `ZoneInfo` object; don't validate the string.
- **Why:**

## Phase 3: checker, solver, infeasibility

### Solver written by Claude
- **Chose:** Claude writes the CP-SAT model; I must be able to explain every variable and constraint.
- **Alternatives:** I write it myself with hints only.
- **Why:**

### Checker before solver
- **Chose:** build the independent checker first.
- **Alternatives:** solver first, checker afterwards.
- **Why:**

### One shared `overlaps()` function
- **Chose:** a single half-open overlap rule in `planner/common.py`, used by FakeCalendar and the checker (and later the solver's tests).
- **Alternatives:** each part writes its own comparison.
- **Why:**

### Schedule = blocks with exact times
- **Chose:** `ScheduledBlock(task_name, start, end)` with minute-precise UTC times.
- **Alternatives:** blocks as solver slot numbers (e.g. slots 36-43).
- **Why:**

### Blocks refer to tasks by name
- **Chose:** `task_name`, with task names required to be unique in a `PlanRequest`.
- **Alternatives:** refer by position in the task list; give each task a separate id.
- **Why:**

### Checker returns every violation
- **Chose:** a list of `Violation(kind, task_name, message)`; empty list = valid.
- **Alternatives:** return True/False; raise an error at the first problem.
- **Why:**

### Day hours checked per local day
- **Chose:** build each block's allowed window from its local date in `request.timezone` (zoneinfo applies that day's offset); a block must fit inside one day's window.
- **Alternatives:** convert `day_start`/`day_end` to a fixed UTC time once; allow a block to span two days' windows.
- **Why:**

### `day_end = 00:00` is rejected
- **Chose:** schema error; "until midnight" means leaving `day_end` empty.
- **Alternatives:** read 00:00 as end of day; read it as start of day.
- **Why:**

### Lengths in whole 15-minute steps
- **Chose:** the schema requires `duration_min`, `min_block_min`, `max_block_min` to be multiples of 15; the parser rounds.
- **Alternatives:** allow any minutes and let the solver round (then its totals never match exactly); make the checker tolerate rounding.
- **Why:**

### Shortest block = min(min_block, duration)
- **Chose:** `Task.shortest_block_min`, one definition used by checker and solver.
- **Alternatives:** reject tasks shorter than their minimum block; let the solver and checker each handle it.
- **Why:**

### Totals must match exactly
- **Chose:** too little and too much scheduled time are both violations (`WRONG_TOTAL`).
- **Alternatives:** only flag too little ("unscheduled minutes"), allow extra time.
- **Why:**

### Daily cap counts real minutes per local day
- **Chose:** minutes from UTC subtraction, grouped by Zurich date; blocks crossing local midnight are split.
- **Alternatives:** wall-clock subtraction; group by UTC date; count a block only on its start day.
- **Why:**

### Time-indexed model (15-minute slots)
- **Chose:** the brief's slot model: yes/no variables `x[i,t]` (task i uses slot t) and `s[i,t]` (a block starts at t).
- **Alternatives:** CP-SAT interval variables with `AddNoOverlap`.
- **Why:**

### Max block length as an extra constraint
- **Chose:** add "any `max_block` + 1 slots in a row have at most `max_block` used", which the brief's formula is missing.
- **Alternatives:** drop `max_block_min` from the solver and rely on the parser never setting it.
- **Why:**

### Slots in UTC, horizon rounded inward
- **Chose:** slots are real 15-minute steps from `horizon_start` rounded up to a quarter hour; only whole slots inside the horizon.
- **Alternatives:** slots in local wall-clock time; round the horizon outward.
- **Why:**

### A slot is busy if an event touches it at all
- **Chose:** mark the whole slot busy when any event overlaps it (e.g. 10:05-10:50 blocks 10:00 and 10:45).
- **Alternatives:** smaller slots (5 min) to lose less free time; allow partly busy slots.
- **Why:**

### Grid keeps each reason separate
- **Chose:** separate lists `busy`, `outside_day_hours`, `in_blocked_window`, plus per-task deadline/earliest slot numbers.
- **Alternatives:** one merged "allowed" list per task.
- **Why:**

### Grid is a frozen dataclass, not a Pydantic schema
- **Chose:** `@dataclass(frozen=True)`, since it is internal and built by our own code.
- **Alternatives:** a `Schema` subclass with validation.
- **Why:**

### Day hours in the grid use a different method from the checker
- **Chose:** compare each slot's local clock times; the checker builds a per-day window.
- **Alternatives:** share one day-hours function between checker and solver.
- **Why:**

### OR-Tools added as a dependency
- **Chose:** `ortools>=9.15.6755` (the brief's solver), API checked against 9.15.6755.
- **Alternatives:** PuLP or another MILP library; a hand-written greedy scheduler.
- **Why:**

### Forbidden slots as `x == 0` rules, not missing variables
- **Chose:** create `x[i][t]` for every slot and add a rule `x[i][t] == 0` where the task may not go.
- **Alternatives:** only create variables for allowed slots (smaller model).
- **Why:**

### Solver time limit and result status
- **Chose:** 10 s limit; return `OPTIMAL`, `FEASIBLE` (valid but not proven best), `INFEASIBLE` or `TIMED_OUT`; raise only on `MODEL_INVALID`.
- **Alternatives:** no time limit; raise an exception for infeasible requests; treat `FEASIBLE` as a failure.
- **Why:**

### Solver tests are judged by the checker
- **Chose:** every solver test runs `check()` on the result and expects no violations.
- **Alternatives:** compare against hand-written expected schedules only.
- **Why:**
