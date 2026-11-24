# Progress log

## 2026-11-17 — Phase 0 (repo skeleton), in progress

**Done**
- Step 1: `git init`, `.gitignore` covering secrets (.env, OAuth token/client files),
  venv, caches, personal settings. Verified with `git check-ignore`.
- Step 2: `pyproject.toml` (Python 3.13, uv_build backend with flat layout),
  dev group: ruff, mypy, pytest, pre-commit. `uv.lock` committed.
- Decisions: Python 3.13 (not 3.14: C-extension wheels such as OR-Tools lag new
  Pythons), flat layout as in the brief, mypy in strict mode.

**Problem found**
- The repo was in `~/Documents`, which iCloud Drive syncs. iCloud sets the macOS
  "hidden" flag on files in `.venv/`, and Python 3.13 skips hidden `.pth` files, so
  `import planner` failed. Fix: move the repo to `~/code/calendar-planner` (outside
  iCloud) and recreate `.venv` with `uv sync`.

## 2026-11-20 — Phase 0 (repo skeleton), done

**Done**
- `import planner` works from `~/code/calendar-planner`.
- Step 3: six subpackages from the brief, each with a docstring stating its job.
  `tests/test_smoke.py` imports each one (parametrized, so failures are reported per
  package).
- Step 4: ruff, mypy (strict) and pytest (`--strict-markers`) configured in
  `pyproject.toml`. ruff skips `docs/` so the brief is never reformatted.
- Step 5: pre-commit with local hooks that call `uv run` (same versions as `uv.lock`,
  mypy sees project dependencies), plus detect-private-key, large-file, YAML/TOML checks.
- Step 6: GitHub Actions CI runs `uv sync --locked` and the four checks on every push
  and PR. Green on GitHub (`swarilord/calendar-planner`, public).
- Pushing uses a fine-grained token (this repo only, Contents + Workflows, 90 days),
  stored in the macOS Keychain.

**Problems found**
- First CI run failed: `astral-sh/setup-uv@v10` does not exist, because setup-uv only
  publishes exact tags. Fixed by pinning `v10.4.0`. Lesson: check that a tag exists,
  not only which release is newest.

**Next**
- Write `docs/decisions.md` entries (in my own words): Python 3.13, flat layout,
  mypy strict, repo outside iCloud, local pre-commit hooks via `uv run`, pre-commit
  plus CI.
- Phase 1: throwaway "hello agent" in ADK with `get_now()`.

## 2026-11-20 — Phase 1 (hello agent), done

**Done**
- `google-adk` 2.15.0 added (checked against the adk.dev quickstart). Gemini key in a
  root `.env` (ADK walks up from the agent folder to find it). `.env.example` committed.
- `experiments/hello_agent/`: throwaway ADK agent with one tool, `get_now()`.
  `describe_time(moment)` holds the logic so tests use fixed moments, including both
  2026 DST switches; `get_now()` only reads the clock. Returns a dict with labelled
  fields (UTC, Zurich, weekday, status) so the LLM gets facts, not work.
- `experiments/hello_agent/trace.py` prints each step of the agent loop. Verified:
  Gemini calls `get_now` for "what day is it" and "hours until midnight", not for
  "capital of Switzerland".
- mypy folder list moved into `[tool.mypy] files`, so tests/ and experiments/ are
  type-checked in pre-commit and CI too.
- gitleaks v8.30.0 pre-commit hook. Tested on a fake `AIza...` key and on the real key.

**Problems found**
- `adk run` hung silently: `gemini-flash-latest` (and 3.7/3.8 flash) returned 503
  "high demand" and ADK retried without printing anything. Pinned `gemini-3.6-flash`.
  `gemini-2.5-flash` is retired for new users.
- A break-test swapped two 13-character strings within one second, so Python reused a
  stale `__pycache__` file. Artefact of the test method, not a code bug.
- gitleaks is built from Go source on first install (minutes); the first attempt
  failed on a network reset but pre-commit still exited 0.

**Next**
- `docs/decisions.md` entries in my own words (Phase 0 list above, plus: hello agent
  in `experiments/`, pinned model name, dict tool results, gitleaks).
- Phase 2: Pydantic schemas, `CalendarBackend`, `FakeCalendar`.
- Later (Phase 4): give the real agent a timeout and a clear error when Gemini is down.

## 2026-11-22 — Phase 2 (schemas, CalendarBackend, FakeCalendar), done

**Done**
- `docs/decisions.md` is updated during work: Chose + Alternatives filled in,
  Why left for me (rule added to CLAUDE.md).
- `planner/common.py`: `Schema` base (frozen, extra="forbid") and `UtcDatetime`
  (timezone required, converted to UTC). Pydantic 2.14.4 as a direct dependency,
  pydantic mypy plugin on.
- `planner/calendar/models.py`: `NewEvent`, `Event` (id, `created_by_planner`,
  `plan_id`), `EventChanges` (None = leave as is).
- `planner/calendar/backend.py`: `CalendarBackend` Protocol plus `EventNotFoundError`
  and `NotOwnedError`.
- `planner/calendar/fake.py`: `FakeCalendar`. In-memory dict, JSON loading,
  deterministic ids, half-open overlap, updates rebuilt with `model_validate`, and
  one ownership gate (`_owned_event`) for update and delete.
- `planner/parser/schemas.py`: `Task`, `Window`, `PlanRequest`. Rejects nonsense on
  any calendar; calendar-specific infeasibility is left to the solver. Times of day
  stay local.
- 60 tests. Break-tests confirmed the ownership gate, the interface fit (mypy), the
  overlap boundary, the timezone and horizon checks.

**Problems found**
- A same-length rename restored within one second left a stale `.mypy_cache`, so
  mypy reported errors in correct code. Clear `__pycache__` and `.mypy_cache` after
  break-tests.

**Next**
- Fill in the blank Why lines in `docs/decisions.md` (Phases 0–2).
- Phase 3: checker, CP-SAT solver, infeasibility explanations. First decide:
  do I write the solver myself with hints, or does Claude write it?

**Open questions**
- Before putting the repo link on my CV: keep `CLAUDE.md` and the Claude co-author
  lines public, or remove them from history?

## 2026-11-23 — Phase 3 (checker, solver, infeasibility), done

**Done**
- `planner/schedule.py`: `ScheduledBlock(task_name, start, end)` and `Schedule`.
- `planner/checker/check.py`: independent checker, 12 violation kinds, returns every
  violation. Exact minutes in UTC; day hours and the daily cap per local day (DST-safe).
  `GRANULARITY_MIN = 15` and `Task.shortest_block_min` added to the schema.
- `planner/solver/grid.py`: horizon cut into 15-min UTC slots (rounded inward); per
  slot: local day, busy (rounded outward), outside day hours; slots per blocked window.
- `planner/solver/model.py`: CP-SAT model (OR-Tools 9.15.6755). Variables x (slot
  used) and s (block starts). Rules: exact totals, forbidden slots, one task per slot,
  block starts, min/max block length, daily cap. Objective: 4 per block + 1 per slot
  before 8:00 or from 20:00. Redundant rule `#blocks >= ceil(duration / max_block)`.
- Infeasibility: each relaxable rule group has a switch. Normal solve fixes switches
  on; if infeasible, a second pass uses them as assumptions, reads CP-SAT's core and
  shrinks it, giving `Conflict(rule, task_name, description)` in Zurich time.
- 164 tests. Solver tests are judged by the checker, plus 25 seeded random requests
  (400 checked once). Break-tests on clashes, day hours, min block, daily cap, core.

**Problems found**
- The brief's formula has no max-block constraint; added as rule 7.
- A random request needed >10 s to prove optimality (bound stuck below the found plan);
  the redundant block-count rule made it 0.05 s.
- Assumptions in every solve made tests 10x slower: hence two passes. Explaining takes
  about 1.5-2.7 s.
- `sufficient_assumptions_for_infeasibility` returns variable indices, not list
  positions, and its set is not minimal (blamed "30-min blocks" for 20 h in one day).
  Both found by testing; docstrings don't say.

**Next**
- Push the unpushed commits and check that CI is green with OR-Tools.
- Fill in the blank Why lines in `docs/decisions.md` (Phases 0-3).
- Phase 4: DSPy parser + ADK agent tools, end to end on the FakeCalendar. Give the
  agent a timeout and a clear error when Gemini is down.

**Open questions**
- Before putting the repo link on my CV: keep `CLAUDE.md` and the Claude co-author
  lines public, or remove them from history?
- Explanations give one reason, not all; is that enough for the agent, or should it
  re-solve after a fix to find the next one?
- Many plans tie on the objective, so CP-SAT may pick different ones between runs.
  Fine for validity tests; decide before Phase 5 evals whether plans must be
  reproducible.

## 2026-11-24 — Phase 4 built, Phase 5 and 6 pipelines built

**Done**
- Phase 4.1 parser: DSPy 3.5.0 signature with `PlanRequest` output, instructions in
  `planner/parser/prompts/parser_v1.md`, no hidden JSON retry, Pydantic's exact
  error reasons in `ParseResult`; `DummyLM` tests. First live run found and fixed
  two problems: Gemini 3 "thinking" took 56 s (now `reasoning_effort="low"`,
  ~13 s) and "leave fields empty" produced empty tags (prompt now says per field).
- Phase 4.2 agent tools (`PlannerTools`): get_now, get_events, get_free_slots,
  propose/revise/explain plans; drafts only, the checker runs on every plan.
- Solver preferences: earlier is better (real cost), lunch 11-12 as a soft cost,
  evenings strongly avoided. Weights 64 / 60 / 100 / 1, each derived from a trade
  and tested (6h, 8h, 10h tasks pause for lunch; next morning beats 22:00).
- Phase 4.3 ADK agent: instruction `agent_v1.md`, six tools, 30 s timeout + one
  retry for every Gemini call (`planner/llm.py`), clear `AgentUnavailableError`,
  parser outages returned as `status: "unavailable"`; `ScriptedGemini` tests run
  the real ADK loop without a key. Demo: `experiments/planner_agent/chat.py`.
  Model switchable with `PLANNER_MODEL`.
- Phase 5: 50 eval cases (35 train / 15 test, conventions in `evals/README.md`,
  drafted by Claude, reviewed by Claude and me), `score_parse` with categorised
  mistakes, Baseline A (direct) and B (parser + solver) judged against the gold
  request, runner with `--pause`, early stop on outages. Baseline A is judged on
  its schedule only (its task list is lenient).
- Phase 6: GEPA pipeline (`planner/evals/optimize.py`): 20 train cases to reflect
  on, 15 to select, test split never used; score + written feedback; result saved
  as a new prompt version.
- 348 tests.

**First (partial) numbers, gemini-3.5-flash-lite, train split, not comparable yet**
- B: 11/11 success, parse exact 45% (mostly `wrong_horizon`, which did not hurt plans).
- A: 14/18 success; 2 invalid, 2 wrong totals (before the fairness fix).

**Problems found**
- Gemini quota: 503/504 overload on most flash models, then 429 per-minute limits
  on the free tier (`--pause 5` keeps a run under ~12 calls per minute).
- A parser timeout inside a tool crashed the chat (fixed: `ParserUnavailableError`).
- "Fit 20 hours of revision into tomorrow" is feasible under our rules (~22 h free).

**Next**
1. Phase 4 live chat run (4 example requests), then the Phase 4 host-call questions.
2. Full baseline runs on the train split, same model, with `--pause 5`.
3. GEPA run (`--budget 150`), read the v1 → v2 diff.
4. Final scores on the test split: A, B with v1, B with v2.
5. Error analysis, README with results table.
6. Then Phase 7 (Google Calendar), 9 (deploy, README GIF), 8 (UI).

**Open questions**
- Billing for the Gemini key, to remove the quota limit for GEPA?
- A default daily work limit, so "20 hours tomorrow" is refused?
- The agent used `revise_plan` for a new request ("20 hours tomorrow"); note for
  error analysis, maybe a prompt rule.
- Repo visibility: keep `CLAUDE.md` and co-author lines public?
- Blank Why lines in `docs/decisions.md` (Phases 0-6).
