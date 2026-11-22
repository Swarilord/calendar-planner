# Calendar Planning Agent

The full project brief is in `docs/brief.md`. It is the source of truth for scope,
architecture and stack. Read it at the start of every session. Where it and this file
disagree about how we work together, this file wins.

## Who I am and how we work

I'm a 2nd-year maths student at ETH Zürich: intermediate Python and C++, no ML, web or
agent experience. I'm building this for Google SWE intern host calls from December 2026,
where I must explain every file and every decision without notes.

**You write most of the code. I make sure I understand all of it.**

- Explain the concept before writing code: what it is, why we need it, a tiny example.
  Assume I'm smart but new to the topic. Use everyday analogies, not maths ones.
- Work in small steps. Each step has a test and ends in a commit I could explain.
- After each step, walk me through the diff: what each part does and why it's written
  that way, not another way. Point out the 1–2 lines that matter most.
- Don't move on while I have an open question. If my explanation back to you is wrong
  or vague, say so directly and correct it.
- Exception, the CP-SAT model (`planner/solver/`): I derive it on paper first. Before
  Phase 3, ask me whether I write it myself with hints only, or you write it. Record my
  answer here: **Solver written by: Claude** (decided 2026-11-22). I must still be able to explain
  every variable and constraint, so walk me through the model before and after coding.
- Stick to the stack in the brief. Propose a new library only with a reason and the
  alternative.
- Tell me honestly when something is overkill, or when I'm stuck on the wrong problem.

## Session ritual

**Start:** read `docs/progress.md`, say in 2–3 lines where we left off, and ask what I
want to work on today.

**End (when I say "wrap up"):**
1. Update `docs/progress.md`: date, what was done, what's next, open questions.
2. Remind me to fill in any blank "Why" lines in `docs/decisions.md`. Review them, but
   don't write the "Why" for me.
3. At the end of each roadmap phase, ask me 3 host-call-style questions about what we
   built and correct my answers.

**During work:** every time we make a design choice, add an entry to `docs/decisions.md`
right away, under the current phase: fill in **Chose** and **Alternatives**, leave
**Why:** blank for me.

## Commands

```bash
uv sync                 # install dependencies
uv run pytest           # tests
uv run ruff check .     # lint
uv run ruff format .    # format
uv run mypy             # type check (folders set in pyproject.toml)
```

Run lint, type checks and tests before every commit. Never commit with failing checks.

## Rules that never bend

- No secrets in git, ever. API keys and OAuth tokens live in `.env` and token files that
  are in `.gitignore`. If you see a secret about to be committed, stop and tell me.
- Tests and evals use `FakeCalendar`, never the real Google Calendar.
- The app only edits or deletes calendar events it created itself (tagged with
  `created_by=planner`). Applying a plan must be idempotent.
- Store times in UTC, show them in Europe/Zurich, and test daylight-saving switches.
- ADK, Gemini, DSPy, OR-Tools and the Calendar API change fast. Check the current docs
  before giving API details, and tell me which version you checked against.
- Prompts live in versioned files. Every eval result records the prompt version and
  model name.

## Roadmap

0. Repo skeleton, tooling, CI
1. Throwaway "hello agent" in ADK with `get_now()`
2. Pydantic schemas, `CalendarBackend`, `FakeCalendar`
3. Checker, CP-SAT solver, infeasibility explanations
4. DSPy parser + ADK agent tools, end to end on the fake calendar
5. Eval data, Baseline A vs B, error analysis
6. APO with GEPA
7. Real Google Calendar (OAuth, tagged events, idempotent apply)
8. FastAPI backend + React week view
9. Docker, Cloud Run, README with demo GIF
