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

### Objective weights and "unpleasant" slots
- **Chose:** `BLOCK_COST = 4`, `UNPLEASANT_SLOT_COST = 1`; slots before 08:00 or from 20:00 local are unpleasant. One extra block = one hour of unpleasant time.
- **Alternatives:** only minimise blocks; make the evening hours part of the request; other weights.
- **Why:**

### Daily cap rounded down to whole slots
- **Chose:** `cap // 15` slots per local day (e.g. 100 min allows 90).
- **Alternatives:** round up; require the cap to be a multiple of 15 in the schema.
- **Why:**

### Redundant "minimum number of blocks" rule
- **Chose:** add `sum(s[i]) >= ceil(duration / max_block)`; it removes no valid plan, but a random test needed >10 s to prove optimality without it and 0.05 s with it.
- **Alternatives:** accept `FEASIBLE` results; raise the time limit; switch to interval variables.
- **Why:**

### Random requests as a solver test
- **Chose:** 25 seeded random calendars; every solved plan must pass the checker (400 seeds checked once by hand).
- **Alternatives:** only hand-written cases; Hypothesis (in the brief's stack) for property-based tests.
- **Why:**

### Which rules get a switch
- **Chose:** switches for each task's deadline, earliest start and block lengths, the day hours, each blocked window, and the daily cap. Always on: each task's total, existing events, the horizon.
- **Alternatives:** a switch for every single constraint; also allow relaxing durations or events.
- **Why:**

### Blocked windows kept per window in the grid
- **Chose:** `blocked_slots: list[list[int]]`, one list per window, so an explanation can name "keep Mon 09:00-12:00 free".
- **Alternatives:** one merged `in_blocked_window` list (could only say "a blocked window").
- **Why:**

### Two passes: fast solve, then explain
- **Chose:** normal solve with every switch fixed on; only if infeasible, rebuild with switches as assumptions. Measured: switches as assumptions in every solve made the tests 10x slower; explaining takes about 1.5-2.7 s.
- **Alternatives:** always solve with assumptions (one model, simpler code).
- **Why:**

### Shrink CP-SAT's core
- **Chose:** after `sufficient_assumptions_for_infeasibility`, drop each switch and re-solve; keep it only if the request becomes possible without it.
- **Alternatives:** report CP-SAT's core as it is (it blamed "blocks of at least 30 min" for "20 h into one day").
- **Why:**

### Explanation as structured conflicts
- **Chose:** `Conflict(rule, task_name, description)` with times shown in Zurich; the agent turns them into a sentence.
- **Alternatives:** one finished sentence from the solver; only the rule names.
- **Why:**

## Phase 4: parser and agent tools

### DSPy 3.5.0, pinned exactly
- **Chose:** `dspy==3.5.0` (current release; the docs I checked describe it; native Gemini without LiteLLM).
- **Alternatives:** 3.4.1 (older, more tutorials online, different default prompt format); a hand-written prompt with the plain Gemini SDK.
- **Why:**

### No hidden retry in the parser
- **Chose:** `XMLAdapter(use_json_adapter_fallback=False)`: one `parse()` is exactly one LM call.
- **Alternatives:** keep DSPy's default, which silently asks again in JSON format when the first answer is invalid.
- **Why:**

### Parser returns errors instead of raising
- **Chose:** `ParseResult(request | None, errors, prompt_version, model)`, with Pydantic's exact reasons (e.g. `tasks.0.duration_min: must be a multiple of 15 minutes`).
- **Alternatives:** let the exception propagate; return only "failed".
- **Why:**

### Instructions in a versioned text file
- **Chose:** `planner/parser/prompts/parser_v1.md`, loaded with `with_instructions`; a test checks it states the same granularity as the schema.
- **Alternatives:** the signature docstring in code; a DSPy JSON state file from the start.
- **Why:**

### Rules restated in words for the LLM
- **Chose:** the instruction spells out offsets, multiples of 15 (rounded up), local day hours, relative dates, recurring tasks, default horizon.
- **Alternatives:** rely on the schema's field names only and let validation reject mistakes.
- **Why:**

### Tests use DummyLM; live check is a manual script
- **Chose:** `dspy.utils.DummyLM` in tests; `experiments/parse_live.py` for a real Gemini call with my key.
- **Alternatives:** call Gemini in tests (needs a key in CI, costs money, not deterministic); mock DSPy internals.
- **Why:**

### mypy overrides for DSPy
- **Chose:** `ignore_missing_imports` for `dspy.*` and `disallow_subclassing_any = false` only for `planner.parser.parse`.
- **Alternatives:** write stub files for DSPy; turn off strict mode; `# type: ignore` on each line.
- **Why:**

### Gemini thinking level "low" for the parser
- **Chose:** `reasoning_effort="low"` (measured on the brief's example 1: 12.7 s and valid, vs 56 s at the default level).
- **Alternatives:** the model's default (high); "minimal"; a different model.
- **Why:**

### Unmentioned fields spelled out per field
- **Chose:** the instruction says which fields are null (self-closing tag), which get a default (`min_block_min` 30) and which are empty lists.
- **Alternatives:** "leave optional fields empty" (Gemini wrote empty tags, which Pydantic rejected); make the schema turn empty text into None.
- **Why:**

### A prompt version is frozen once evaluated
- **Chose:** `parser_v1.md` may still change until its first eval in Phase 5; after that, every change is a new file (`v2`, ...).
- **Alternatives:** a new version for every edit from the start; edit in place forever (eval results can no longer be traced to a prompt).
- **Why:**

### Tools as methods of one class with injected parts
- **Chose:** `PlannerTools(calendar, parser, clock)`; tests pass `FakeCalendar`, a fake parser and a fixed clock.
- **Alternatives:** module-level functions using global objects; build the real calendar and parser inside each tool.
- **Why:**

### Tool errors are returned, not raised
- **Chose:** every tool returns a dict with `status` (`ok`, `error`, `infeasible`) and a message the agent can read.
- **Alternatives:** raise exceptions and let ADK report them.
- **Why:**

### Tools never write to the calendar
- **Chose:** `propose_plan`/`revise_plan` only store drafts (`plan-1`, `plan-2`, ...) in memory; a test checks the calendar is unchanged.
- **Alternatives:** an `apply_plan` agent tool (the brief rules this out: writes only after a Confirm click).
- **Why:**

### The checker runs inside `propose_plan`
- **Chose:** every solved plan is checked before the agent sees it; violations become an "internal error".
- **Alternatives:** check only in tests and evals.
- **Why:**

### `revise_plan` re-parses the original text plus the change
- **Chose:** text = original request + "Change: ...", giving a new draft id; old drafts are kept.
- **Alternatives:** let the parser edit the old `PlanRequest` directly; overwrite the old draft.
- **Why:**

### All existing events count as busy, including the planner's own
- **Chose:** for now the solver avoids every event; moving earlier planner blocks (brief examples 2 and 3) is left for Phase 7.
- **Alternatives:** treat events with `created_by_planner` as movable now.
- **Why:**

### Agent sees Zurich time only
- **Chose:** tool outputs show local times like "Tue 24 Nov 09:00"; tool inputs must be ISO 8601 with an offset.
- **Alternatives:** UTC everywhere in tool outputs; accept times without an offset and assume Zurich.
- **Why:**

### Lunch as a soft preference
- **Chose:** `lunch_start`/`lunch_end` on `PlanRequest`, default 11:00-12:00 local; lunch slots cost extra but may be used. "Keep lunch free" becomes a normal blocked window.
- **Alternatives:** lunch as a hard blocked window (a full day becomes infeasible just because of lunch); no lunch handling.
- **Why:**

### Earlier is better, as a real cost
- **Chose:** every used slot costs its slot number, so one hour of work done one hour later costs a quarter of a block. A 6h task on a free day becomes 08-11 + 12-15.
- **Alternatives:** earliness only as a tie-breaker (gave 12-18 in one block, and was slow to prove); a cost per day of delay.
- **Why:**

### Objective weights revised
- **Chose:** block 64, lunch 60 per slot, evening/early 100 per slot, delay 1 per slot-step. Lunch hour (240) > extra block + delay of all work after lunch (at most 64 + 128 = 192); evening slot (100) > overnight wait (48), so work moves to the next morning. (Lunch 32 was too low: 8h tasks worked through lunch.)
- **Alternatives:** the Phase 3 weights (block 4, evening 1), which would put work at 22:00 rather than 9:00 next day once earliness counts.
- **Why:**

### Gym and dinner are not modelled
- **Chose:** nothing new; work after 20:00 is strongly discouraged, so evenings stay free. Gym can be a normal task with an earliest start of 20:00.
- **Alternatives:** optional low-priority tasks, an "after the day's last work block" rule, per-task time preferences (later extension, after Phase 6).
- **Why:**

### Random solver test accepts FEASIBLE
- **Chose:** the random test requires a valid plan (checker passes) with status OPTIMAL or FEASIBLE.
- **Alternatives:** require OPTIMAL (could fail randomly on slower CI machines: one request took 7.4 s of the 10 s limit locally).
- **Why:**

### One module for all Gemini settings
- **Chose:** `planner/llm.py` holds model, timeout, retries and thinking level for both the parser (DSPy, timeout in seconds) and the agent (google-genai, timeout in milliseconds).
- **Alternatives:** settings next to each caller (the units differ, so copying `30` would give the agent a 0.03 s timeout).
- **Why:**

### Gemini calls: 30 s timeout, one retry, low thinking
- **Chose:** every call gives up after 30 s per attempt, retries once, then the agent raises `AgentUnavailableError` with a clear message. Tested against a local server that never answers.
- **Alternatives:** library defaults (the Phase 1 hang: no reply and no error); no retry; more retries.
- **Why:**

### Agent instruction in a versioned file
- **Chose:** `planner/agent/prompts/agent_v1.md`, the brief's behaviour rules; a test checks it has no `{...}` (ADK reads those as session-state variables).
- **Alternatives:** an instruction string in code; a DSPy-generated prompt for the agent too.
- **Why:**

### Agent tests with a scripted fake model
- **Chose:** `ScriptedGemini(BaseLlm)` returns scripted tool calls and answers, so the real ADK loop runs in tests without a key.
- **Alternatives:** only test the tools; call real Gemini in tests; mock ADK's runner.
- **Why:**

### Runnable demo stays in experiments/
- **Chose:** `experiments/planner_agent/` builds the agent on a FakeCalendar with two weeks of lectures and the real parser; `chat.py` shows each tool call.
- **Alternatives:** a demo inside `planner/`; a JSON calendar file with fixed dates (would be in the past next week).
- **Why:**

### Model chosen by environment variable
- **Chose:** `PLANNER_MODEL` overrides `DEFAULT_MODEL` (gemini-3.6-flash) for parser and agent, read at call time. On 2026-11-24 most flash models returned 503/504 and only the lite models answered.
- **Alternatives:** edit the constant in code each time; automatic fallback to another model (hides which model produced an answer, which evals must record).
- **Why:**

### Parser outages are their own error and status
- **Chose:** the parser turns any DSPy `LMError` into `ParserUnavailableError`; `propose_plan`/`revise_plan` return `status: "unavailable"`, and the agent asks the user to try again. Found in the first live run: a parser timeout inside a tool crashed the chat.
- **Alternatives:** let it propagate (crash with a traceback); report it as a parse error with details (would wrongly tell the user their request was unclear).
- **Why:**

## Phase 5: evals

### Eval data drafted and reviewed by Claude
- **Chose:** Claude drafts and reviews all 50 cases; automatic checks (schema, conventions, solver agrees with the feasibility label) back it up; judgement calls are listed in `evals/README.md`.
- **Alternatives:** Claude drafts, I review every case; I write all cases; Gemini generates them (Gemini grading Gemini).
- **Why:**

### 50 cases, 35 train / 15 held-out test
- **Chose:** a hand-balanced split so the test part has infeasible, DST, recurring, multi-task and next-week cases.
- **Alternatives:** random split; more cases (more calls and review time); no held-out part.
- **Why:**

### Dataset as JSON Lines with local times
- **Chose:** `evals/cases_v1.jsonl` (one case per line, Zurich times with offsets) plus named calendars in `evals/calendars.json`.
- **Alternatives:** cases written as Python code; UTC times; a calendar copied into every case.
- **Why:**

### Gold conventions written down
- **Chose:** `evals/README.md` states every judgement rule (evening = 18-24, horizon, "every day" includes today, ...), matching `parser_v1.md`.
- **Alternatives:** decide case by case without written rules.
- **Why:**

### Parser scored as a list of categorised mistakes
- **Chose:** `score_parse(gold, predicted)` lists every mistake (`missing_task`, `wrong_deadline`, `wrong_blocked`, ...); a case is exact if there are none. Counting categories is the error analysis.
- **Alternatives:** one number per case (e.g. % of fields correct); an LLM judge comparing the two requests.
- **Why:**

### Tasks paired by similarity, names not scored
- **Chose:** pair gold and predicted tasks greedily by similarity (same deadline 2, same duration 1, shared name words up to 1); unpaired tasks are missing or extra.
- **Alternatives:** pair by exact name (fails on "Analysis" vs "Analysis sheet"); pair by list order; optimal assignment (more code, same result on small task lists).
- **Why:**

### Both baselines judged against the gold request
- **Chose:** each baseline's schedule is checked against the gold `PlanRequest`; success = the right "impossible", or a feasible plan with no violations.
- **Alternatives:** check Baseline B against the parser's own request (always valid; hides every misunderstanding).
- **Why:**

### Baselines report their tasks; blocks renamed to gold names
- **Chose:** both baselines return the tasks they understood; `rename_blocks` maps them to gold names via `match_tasks`, so the checker can judge them; unmatched tasks stay as invented.
- **Alternatives:** require gold task names in the output (impossible without leaking the answer); match blocks to tasks by time.
- **Why:**

### Baseline A gets the same conventions in words
- **Chose:** `planner/evals/prompts/direct_v1.md` states the same date/duration conventions as `parser_v1.md` plus the scheduling rules, so only "who schedules" differs.
- **Alternatives:** a minimal prompt for A (an unfair comparison).
- **Why:**

### Outages are counted, not scored
- **Chose:** an "unavailable" outcome is recorded but left out of every rate.
- **Alternatives:** count it as a failure (mixes Google's load with model quality); retry until it works (runs could take hours).
- **Why:**

### Eval results saved as JSON files in the repo
- **Chose:** `evals/results/<time>_<baseline>_<model>_<split>.json` with model, prompt version, summary and every outcome.
- **Alternatives:** only print the summary; a database; an experiment-tracking service.
- **Why:**

## Phase 6: prompt optimisation (GEPA)

### GEPA budget set as parser calls
- **Chose:** `max_metric_calls` (default 150) instead of DSPy's `auto="light"` preset; one metric call is one Gemini parse, so the cost is known before the run.
- **Alternatives:** `auto="light"/"medium"/"heavy"` (call count hidden); a time limit.
- **Why:**

### GEPA uses only the train split: 20 to reflect on, 15 to select
- **Chose:** the first 20 train cases (by id) are GEPA's trainset, the other 15 its valset; the 15 test cases are only used for the final v1 vs v2 comparison. A test checks this.
- **Alternatives:** use all 50 cases (the before/after score would measure memorisation); random split each run.
- **Why:**

### Metric: score plus written feedback
- **Chose:** 1.0 if exact, minus 0.25 per plan-changing mistake, minus 0.1 for `wrong_horizon`, 0 if invalid; feedback lists each finding ("wrong_deadline: expected ..., got ...") for the reflection LM.
- **Alternatives:** exact/not exact only (no partial credit, no hints); score only, no feedback (GEPA's main strength unused); downstream plan success as the score.
- **Why:**

### Optimised prompt saved as a new version
- **Chose:** GEPA's best instructions become `parser_v2.md`; existing versions are never overwritten (enforced in code and tested).
- **Alternatives:** overwrite `parser_v1.md`; keep the result only as a DSPy state JSON.
- **Why:**

### More retries for offline runs
- **Chose:** GEPA's parser and reflection LMs get 8 retries (DSPy waits before each), one thread; the reflection LM uses temperature 1.0.
- **Alternatives:** the app's 1 retry (rate limits would turn cases into failures and mislead GEPA); parallel threads (faster, hits the per-minute quota).
- **Why:**

### Baseline A judged on its schedule, not its task list
- **Chose:** A's task list is a lenient `StatedTask` (name, optional duration and deadline, extra fields ignored), used only to pair its blocks with gold tasks; `match_tasks` accepts anything with those three fields (`TaskLike` protocol). Found in the first live run: c23 failed on an empty `max_block_min` in the side list, though the schedule was never looked at.
- **Alternatives:** keep the strict `Task` schema for A's list (A fails for things that don't affect the user's plan); drop the list and pair blocks by time.
- **Why:**

### Default limits: 07:00 to midnight, 12 h per day
- **Chose:** `day_start` defaults to 07:00 (`day_end` None = midnight) and `max_work_min_per_day` to 720; the user's words override them, and None lifts a limit. Found in the live chat: "20h of revision tomorrow" became a 15-hour all-night block; now it is "impossible: at most 720 min of work per day". Stated in the parser and Baseline A prompts, so both baselines get the same rules.
- **Alternatives:** no defaults (all-night plans are "valid"); a stricter 8 h cap; a default maximum block length (e.g. 3 h).
- **Why:**

### Agent rule: revise_plan only for changes to the current draft
- **Chose:** the agent prompt says a new task or request after a draft is a new plan (`propose_plan`). Found twice in live runs.
- **Alternatives:** let `revise_plan` merge everything (mixes old tasks into new requests); remove `revise_plan`.
- **Why:**

### Gemini free tier only, no billing
- **Chose:** the project runs on the Gemini API free tier; quota limits are handled by `--pause`, the 3-outages stop, `PLANNER_MODEL` (a lighter model with its own quota) and GEPA's budget.
- **Alternatives:** a paid key (no per-minute stalls, faster eval and GEPA runs, costs money); a different free provider for evals (results would no longer be about Gemini).
- **Why:**

### Agent rule: the solver decides feasibility, not the agent
- **Chose:** the agent prompt forbids judging whether a request fits; it always calls `propose_plan`. Found in the live chat: the agent answered "20h of revision tomorrow" itself with wrong arithmetic ("24 hours total") instead of the solver's reason.
- **Alternatives:** let the agent pre-filter obviously impossible requests (saves a call, but its arithmetic is unreliable); a code-level check before the agent replies.
- **Why:**
