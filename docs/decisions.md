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
