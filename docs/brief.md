# Calendar Planning Agent — Project Brief

Nov 17, 2026 · Swarit

## Goal and context

I am building a calendar planning agent. I tell it in plain English what needs doing; it reads my Google Calendar, schedules the work with a constraint solver, and writes the time blocks back after I confirm. The project is for Google SWE intern host matching (EMEA): one project I fully understand and can explain in depth in host calls from December 2026 onward.

How to use this brief: this file is the source of truth for scope. When a decision changes, update it here.

What the project must show:

- An LLM agent that uses tools. Most Google intern teams work on LLM agents, tool integration and prompting, not on training models.
- A clear split of work: the LLM understands language; a deterministic solver does the scheduling.
- Measured quality: an eval set, an error analysis, and automatic prompt optimization (APO) with a before/after score on held-out data.
- Production habits: tests, CI, typed interfaces, logging, safe writes, a deployed web app and a clean README.

About me: 2nd-year maths student at ETH Zürich. Python and C++ at intermediate level. No ML background, no earlier agent or web projects. I am investing serious time and do not want to cut corners.

## What the app does

The user describes tasks and wishes in one message; the app shows a proposed week with new time blocks and writes them to the calendar only after a click on Confirm.

Example requests the app must handle:

1. "Analysis sheet due Thursday 23:59, about 4h. Linear Algebra due Friday noon, about 3h. Revise for the midterm 1h every day. Nothing before 9, keep Wednesday evening free."
2. "I'm sick today, push everything you planned for today to later this week."
3. "Move my study blocks so they don't clash with the new Tuesday lecture."
4. "How much free time do I have on Thursday afternoon?" (read-only question)
5. "Fit 20 hours of revision into tomorrow." (impossible: the app must say why, not produce a broken plan)

**In scope:**

- Plan a set of tasks within a horizon (default: the rest of this week).
- Replan after a change: move, shorten or cancel planned blocks.
- Answer questions about busy and free time.
- Show a preview and require explicit confirmation before any write.
- Only ever change events the app created itself.
- Explain infeasible requests, naming the constraint that cannot be met.

**Not in scope (for now):** reading PDFs or emails, several users or shared calendars, a mobile app, training any model.

## Architecture

The LLM understands the request; the solver builds the schedule.

```text
Web UI ─────────────► FastAPI backend ─────────► Agent (Gemini + ADK)
preview + confirm     auth, plans, traces        talks, picks the next tool
                                                        │ tool calls
                      ┌─────────────────────┬───────────┴──────────┐
                      ▼                     ▼                      ▼
Eval + GEPA ····► Request parser       CP-SAT solver         Calendar tools
offline:          text to PlanRequest  places time blocks    events, free slots
score, tune       (tuned prompt)                                   │
                                                 CalendarBackend interface
                                                    ┌──────────────┴─────────┐
                                                    ▼                        ▼
                                              Fake calendar           Google Calendar
                                              tests and evals         OAuth, tagged writes
```

A request flows from the web UI through the backend to the agent, which calls the parser, solver and calendar tools. Writes happen only through the backend after the user clicks Confirm. The eval harness runs offline and feeds an improved parser prompt back in.

| Layer | Choice |
| --- | --- |
| LLM | Gemini through a Google AI Studio API key: a fast model for agent and parser, a stronger one for GEPA reflection |
| Agent framework | Google Agent Development Kit (ADK), Python |
| Parser and APO | DSPy with the GEPA optimizer |
| Solver | OR-Tools CP-SAT |
| Calendar | Google Calendar API with OAuth 2.0; FakeCalendar for tests |
| Backend | FastAPI, Pydantic, SQLModel with SQLite |
| Frontend | React + TypeScript (Vite) |
| Quality | uv, ruff, mypy or pyright, pytest + Hypothesis, GitHub Actions |
| Deployment | Docker, Cloud Run, Secret Manager |

## The LLM agent

The agent is a Gemini model running in Google's Agent Development Kit (ADK). It handles the conversation and decides which tool to call; it never places time blocks itself and never writes to the calendar without a human click.

Core design decision: the agent splits into two LLM roles plus one deterministic part.

1. Conversation agent (ADK `LlmAgent`): talks to the user, asks clarifying questions, calls tools.
2. Request parser (a separate DSPy module): turns the user's text, the current time and a short calendar summary into a typed `PlanRequest`. This is the part the evals measure and APO optimizes.
3. Solver (OR-Tools CP-SAT, no LLM): turns the `PlanRequest` and the busy times into a schedule.

Tools the conversation agent can call:

| Tool | What it does | Writes? |
| --- | --- | --- |
| `get_now()` | Current date, time and timezone | No |
| `get_events(start, end)` | Compact list of events in a range | No |
| `get_free_slots(start, end, min_minutes)` | Free windows, after busy times are removed | No |
| `propose_plan(request_text)` | Runs parser and solver, stores a draft plan, returns its id and a summary | No (draft only) |
| `revise_plan(plan_id, change_text)` | Re-runs parser and solver with an extra instruction | No (draft only) |
| `explain_infeasible(plan_id)` | Names the constraints that make a request impossible | No |

Applying a plan is not an agent tool. The web UI's Confirm button calls the backend directly, so the model cannot write to the calendar on its own.

The `PlanRequest` schema (Pydantic, used as the parser's structured output):

```python
class Task(BaseModel):
    name: str
    duration_min: int
    deadline: datetime
    earliest_start: datetime | None = None
    min_block_min: int = 30          # no study blocks shorter than this
    max_block_min: int | None = None # e.g. at most 2h in one sitting


class Window(BaseModel):
    start: datetime
    end: datetime


class PlanRequest(BaseModel):
    horizon_start: datetime
    horizon_end: datetime
    tasks: list[Task]
    blocked: list[Window] = []           # "keep Wednesday evening free"
    day_start: time | None = None        # "nothing before 9"
    day_end: time | None = None
    max_work_min_per_day: int | None = None
    timezone: str = "Europe/Zurich"
```

Recurring wishes ("1h every day") are expanded by the parser into one task per day, each with that day as its deadline.

Agent behaviour rules (system prompt):

- Call `get_now()` before interpreting relative dates such as "Thursday" or "next week".
- Ask one clarifying question when a duration or deadline is missing, instead of guessing.
- Always show the draft plan and wait for Confirm; never claim events were created before the backend reports success.
- Keep tool outputs compact (no full event descriptions) so the context stays small.

## Scheduling solver

The schedule comes from an integer program solved with OR-Tools CP-SAT. Time in the horizon is cut into 15-minute slots t = 0 … T−1.

Data: task i needs dᵢ slots, has deadline slot Dᵢ, and may only use its allowed slots Aᵢ (inside day_start/day_end, outside blocked windows, after earliest_start). bₜ = 1 if slot t is busy with an existing event; cₜ is a small cost for unpleasant slots such as late evening; Hₖ is the daily cap for day k; mᵢ is the minimum block length.

Variables: xᵢₜ = 1 if task i uses slot t; sᵢₜ = 1 if a block of task i starts at slot t.

```latex
\begin{aligned}
\min\quad & \alpha \sum_{i,t} s_{i,t} \;+\; \beta \sum_{i,t} c_t\, x_{i,t} \\
\text{s.t.}\quad & \sum_t x_{i,t} = d_i && \forall i \\
& x_{i,t} = 0 && \text{if } t \ge D_i \text{ or } t \notin A_i \\
& \sum_i x_{i,t} \le 1 - b_t && \forall t \\
& s_{i,t} \ge x_{i,t} - x_{i,t-1} && \forall i, t \\
& x_{i,t+j} \ge s_{i,t} && \forall i, t,\; 0 \le j < m_i \\
& \sum_{t \in \text{day } k} \sum_i x_{i,t} \le H_k && \forall k \\
& x_{i,t},\, s_{i,t} \in \{0, 1\}
\end{aligned}
```

The first objective term penalises fragmented work (fewer, longer blocks); the second penalises unpleasant times. Deadlines, busy times and allowed windows are hard constraints.

Infeasible requests: CP-SAT reports INFEASIBLE. To explain why, each group of constraints (one deadline, one blocked window, the daily cap) gets an assumption literal; CP-SAT's sufficient-assumptions feature returns a small set that cannot hold together, which the agent turns into a sentence.

Design questions to explore and write up:

- Time-indexed model (above) vs. CP-SAT interval variables with `AddNoOverlap`: compare speed and code clarity.
- Slot size: 15 vs. 30 minutes, and how solve time grows with horizon length.
- A solver time limit, and what to return if it is hit before the optimum is proven.

## Calendar backends

All calendar access goes through one `CalendarBackend` interface with two implementations: a fake calendar for development, tests and evals, and the real Google Calendar.

```python
class CalendarBackend(Protocol):
    def list_events(self, start: datetime, end: datetime) -> list[Event]: ...
    def create_event(self, event: NewEvent) -> Event: ...
    def update_event(self, event_id: str, changes: EventChanges) -> Event: ...
    def delete_event(self, event_id: str) -> None: ...
```

- **FakeCalendar:** events kept in memory and loadable from a JSON file. Deterministic, so tests and evals never touch the real API.
- **GoogleCalendar:** the Google Calendar API through `google-api-python-client`, with OAuth 2.0 login (`google-auth-oauthlib`). A Google Cloud project with the consent screen in testing mode and me as the test user. Request the narrowest scope that allows reading and writing events.

Rules for writes:

- Every event the app creates carries private extended properties, such as `created_by=planner` and the `plan_id`. The app only ever edits or deletes events with that tag.
- Applying a plan is idempotent: confirming the same plan twice must not create duplicates. Check the tags before inserting.
- Store times in UTC, show them in Europe/Zurich, and test the daylight-saving switches (last Sunday of March and of October).
- Tokens and keys never go into git. Locally they live in `.env` and a token file listed in `.gitignore`; in deployment they live in Secret Manager.

Errors to handle: expired tokens (refresh, else ask the user to log in again), API rate limits (retry with backoff), and an event that changed between preview and Confirm (re-check and re-propose).

## Evaluation

Every result in this project is backed by an automatic score on a fixed test set; the headline comparison is "LLM schedules alone" vs. "LLM parses, solver schedules".

Datasets:

| Set | Size | How it is made | Used for |
| --- | --- | --- | --- |
| Generated | ~200 cases | A script samples a random week (lectures, gym, meetings), tasks and constraints, stores the correct `PlanRequest`, then writes the request in English from templates plus LLM rephrasing. I hand-check a sample of the rephrased text. | Train 100, validation 50, test 50 |
| Hand-written | 30–40 cases | I write realistic, messy requests ("not too early", "before the weekend") and label the correct `PlanRequest` by hand. | Final test only, never seen by APO |
| Infeasible | ~15% of each set | Cases with no valid schedule | Checks that the app says no instead of breaking rules |

The checker is plain Python, independent of the solver. Given a calendar, a `PlanRequest` and a schedule, it reports every violation: overlaps, missed deadlines, blocks outside allowed hours, blocks shorter than the minimum, unscheduled minutes, daily cap exceeded.

Metrics:

| Metric | Meaning |
| --- | --- |
| Valid-schedule rate | Share of feasible cases where the final schedule has zero violations against the gold `PlanRequest` |
| Parse accuracy | Share of cases where the parsed `PlanRequest` matches gold; also per field (durations, deadlines, windows) |
| Infeasibility detection | Precision and recall of saying "impossible" on infeasible cases |
| Cost and latency | Tokens and seconds per request |

Experiments:

1. Baseline A: Gemini writes the schedule directly as JSON, no solver.
2. Baseline B: parser plus solver, with a hand-written parser prompt.
3. Error analysis on B: label every failure on the validation set by type (relative date wrong, duration wrong, missed constraint, timezone, invented task) and count them.
4. Fixes: one change per failure type, re-scored each time; then APO (next section).

Run every configuration at least 3 times and report mean and spread, because LLM output varies between runs.

## Automatic prompt optimization (APO)

APO tunes only the request parser's instructions, using DSPy's GEPA optimizer, and the result is reported once on test data the optimizer never saw.

How it works: GEPA runs the parser on training cases, reads the full traces of what went wrong, has a stronger "reflection" model propose improved instructions, and keeps a candidate only if it scores better on the validation set.

Setup:

- The parser is a DSPy module whose signature is: request text, current time, calendar summary → `PlanRequest`.
- Metric for GEPA: field-level parse accuracy, plus a text explanation of each wrong field. GEPA can use that written feedback, not just the number.
- Train on the generated train split, select on validation, report on the generated test split and the hand-written set.
- Fix a budget (number of metric calls) and record the money and time each run costs.

What to report: a results table with baseline prompt vs. optimized prompt on both test sets (mean and spread over 3 runs), the cost of the optimization run, and a diff of the old and new instructions with my reading of what changed.

Overfitting check: if the optimized prompt gains on generated data but not on hand-written data, it has learned the generator's style. That finding is worth writing up too.

## Web app, backend and deployment

Start in ADK's built-in dev UI; move to my own FastAPI backend and React frontend once the agent and solver work, then deploy on Cloud Run.

Backend (FastAPI):

| Endpoint | Purpose |
| --- | --- |
| `POST /chat` | Send a message; streams the agent's reply, run through ADK's runner |
| `GET /plans/{id}` | Draft plan: existing events plus proposed blocks |
| `POST /plans/{id}/apply` | Writes the plan after the user clicks Confirm; idempotent |
| `POST /plans/{id}/reject` | Discards the draft |
| `GET /auth/login`, `GET /auth/callback` | Google OAuth flow |

Plans, plan items and traces are stored with SQLModel, in SQLite locally.

Frontend (React + TypeScript, Vite): a chat panel next to a week view. Existing events show in grey, proposed blocks are highlighted, with Confirm and Reject buttons. A ready-made calendar component is fine; the point is the agent, not CSS.

Deployment: Docker image on Cloud Run, with the Gemini API key and OAuth secrets in Secret Manager.

Open question: Cloud Run loses local files on restart, so SQLite does not survive there. Choose Firestore or Cloud SQL when deploying, or keep the hosted demo on the fake calendar only.

## Engineering quality

The repo should look like code a team could maintain: typed, tested, linted on every push, and documented with the reasons behind each decision.

Tooling: uv for environments and dependencies, ruff for lint and format, mypy or pyright for types, pytest, and pre-commit hooks.

Tests:

- Solver: small hand-made cases with a known best answer, and property-based tests with Hypothesis (any schedule the solver returns passes the checker).
- Checker: one test per violation type, including edge cases at midnight and on daylight-saving days.
- Fake calendar and the idempotent apply step.
- Agent: tool functions tested directly; one end-to-end test with a stubbed model that returns fixed tool calls.

CI: GitHub Actions runs lint, type checks and tests on every push. The eval suite costs API money, so it runs on manual trigger and writes a results file.

Traces: log every LLM call and tool call (prompt version, input, output, tokens, latency) to a JSONL file or SQLite table. ADK's dev UI shows traces during development.

Prompts as code: prompts live in versioned files, and every eval result records the prompt version and model name.

Repo layout (suggested):

```text
planner/
  agent/       # ADK agent, tools, system prompt
  parser/      # DSPy module, PlanRequest schema
  solver/      # CP-SAT model
  checker/     # independent schedule checker
  calendar/    # CalendarBackend, FakeCalendar, GoogleCalendar
  api/         # FastAPI app
web/           # React frontend
evals/         # generators, datasets, runner, results
tests/
docs/decisions.md
```

README: demo GIF, architecture diagram, how to run locally, results table, design decisions, known limitations. `docs/decisions.md` holds one short entry per decision: what I chose, the alternatives, and why.

## Definition of done

A stranger can clone the repo and run it with the fake calendar using one command. The README shows baseline vs. solver vs. APO scores on held-out data. I can explain every file without looking at it.

## What to learn and what to explain

Learn each topic just before the part of the project that needs it; the goal is to answer the host-call questions below confidently and in my own words.

Learning list:

| Topic | Where |
| --- | --- |
| What an LLM is and how agents work | Karpathy's "Intro to Large Language Models" talk; Anthropic's "Building effective agents" post |
| ADK agents and function tools | ADK docs and quickstart |
| Gemini function calling and structured output | Gemini API docs |
| CP-SAT modelling | OR-Tools docs; the community "CP-SAT Primer" |
| Pydantic models and validation | Pydantic docs |
| OAuth 2.0 basics, Calendar API | Google Calendar API Python quickstart |
| How to design LLM evals and do error analysis | Hamel Husain's posts on evals |
| DSPy signatures and modules, GEPA | DSPy docs and the GEPA tutorial |
| FastAPI, React basics | FastAPI tutorial, React docs |
| Docker, Cloud Run | Docker getting-started guide, Cloud Run quickstart |

APIs for ADK, Gemini and DSPy change quickly: always check the current docs rather than old blog posts.

Questions I must be able to answer in a host call:

1. Why did you split the LLM and the solver? What did baseline A vs. B show?
2. Walk me through your CP-SAT model. Why time slots instead of intervals? What happens to solve time with a longer horizon?
3. How do you know it works? How was the test data made, and what bias could the generator introduce?
4. What did the error analysis find, and which fix helped most?
5. What does GEPA do, how did you avoid overfitting, and what did a run cost?
6. How do you stop the agent from doing damage? (Confirm before write, only edit tagged events, narrow OAuth scope.)
7. What breaks: ambiguous dates, timezones, impossible requests, API errors, run-to-run variance?
8. What would you change to serve a million users?

## Instructions for the AI assistant

You are helping me build this project so that I understand all of it; my learning matters more than speed.

*Updated Nov 17, 2026: I no longer write most of the code myself. I read, run and explain all of it. `CLAUDE.md` holds the detailed working rules.*

- At the start of each session, check `docs/progress.md` and ask what I want to work on.
- Explain the concept before writing code. Keep steps small, each with a test, so I could commit after each one.
- You write the code, then walk me through it line by line until I can explain it back. The one open exception is the CP-SAT model: ask me before Phase 3 whether I write it myself with hints or you write it.
- Stick to the stack in this brief. Propose a new library only with a reason and the alternative.
- Check current documentation for ADK, Gemini, DSPy, OR-Tools and the Calendar API before giving API details; they change often.
- After each finished part of the project, ask me 3 host-call-style questions about what we built and correct my answers.
- Remind me to add an entry to `docs/decisions.md` whenever we make a design choice.
- Tell me honestly when something is overkill or when I am stuck on the wrong problem.
