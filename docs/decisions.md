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
