# calendar-planner

Plan study time into Google Calendar by describing it in a sentence.

You type something like *"Analysis sheet, about 4h, due Thursday evening, keep
Wednesday evening free"*. Gemini turns that into a structured request, a
constraint solver finds slots around your lectures and other events, and
nothing is written to your calendar until you click Confirm.

![Demo](docs/demo.gif)

<sub>Fake calendar with a week of lectures. Typing is sped up and the wait for Gemini is cut.</sub>

## How it works

```
 Web UI (React)          FastAPI backend                 Agent (Gemini + ADK)
 chat + week view ──────► /api/chat ────────────────────► chooses a tool
       │                                                       │
       │ Confirm                                               ▼
       └──────────► /api/plans/{id}/apply        propose_plan: text ─► parser (DSPy + Gemini)
                         │                                      ─► PlanRequest (Pydantic)
                         ▼                                      ─► CP-SAT solver (OR-Tools)
                   apply_plan ──► Google Calendar               ─► checker ─► draft
                   (idempotent,    ("Study plan" calendar,
                    re-checks)      tagged events only)
```

The LLM only handles language. A Gemini agent (Google ADK) talks to you and
calls tools; one of them parses the request into a typed `PlanRequest` using
DSPy. The scheduling itself is an OR-Tools CP-SAT model: deadlines, block
lengths, day hours, a daily limit and a soft lunch break. A separate checker
re-validates every plan before you see it, and when a request can't fit, the
solver reports which constraint is the problem.

Writing to the calendar is kept deliberately boring. The app can only write to
its own "Study plan" calendar (OAuth scope `calendar.app.created`), only after
Confirm, and applying the same plan twice doesn't create duplicates.

## Results

50 hand-checked requests, 15 of them held out for testing,
`gemini-3.5-flash-lite`:

| | Test success |
|---|---|
| Gemini schedules directly | 67-73% (two runs) |
| Gemini parses, solver schedules | 93% |
| Same, with a GEPA-optimised parser prompt | 100% |

The test set is small, so read this as a direction rather than exact numbers.
The remaining mistakes are almost all the parser misreading wording. Details
in [evals/README.md](evals/README.md).

## Running it

You need [uv](https://docs.astral.sh/uv/), Node 24 and a Gemini API key.

```bash
uv sync
cp .env.example .env          # add your GOOGLE_API_KEY
cd web && npm ci && cd ..

uv run uvicorn planner.api.main:app --reload    # backend
cd web && npm run dev                           # frontend: http://localhost:5173
```

This runs on a fake calendar. To use your real one, create a Google Cloud OAuth
client (desktop app) with the Calendar API scopes `calendar.app.created`,
`calendar.events.readonly` and `calendar.calendarlist.readonly`, save it as
`credentials.json`, log in once with `uv run python -m planner.calendar.auth`
and start the backend with `PLANNER_CALENDAR=google`.

Tests run offline: `uv run pytest` and `cd web && npm test`.

With Docker:

```bash
docker build -t calendar-planner .
docker run -p 8080:8080 -e GOOGLE_API_KEY=... calendar-planner
```

## Limitations

- Single user: drafts live in memory and there is one Google login.
- The parser still misreads some phrasings, e.g. "fit 20 hours" becomes a
  20-hour daily limit.
- Free-tier Gemini is sometimes slow or rate-limited.
