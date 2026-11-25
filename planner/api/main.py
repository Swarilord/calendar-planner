"""Entry point for the web backend.

    uv run uvicorn planner.api.main:app --reload             # fake calendar
    PLANNER_CALENDAR=google uv run uvicorn planner.api.main:app

With PLANNER_CALENDAR=google, log in once first: uv run python -m planner.calendar.auth
If the frontend is built (cd web && npm run build), this server also serves it at
http://localhost:8000: one process, as in production.
"""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from planner.agent.tools import PlannerTools
from planner.api.app import create_app
from planner.calendar.auth import get_credentials
from planner.calendar.backend import CalendarBackend
from planner.calendar.demo import demo_events
from planner.calendar.fake import FakeCalendar
from planner.calendar.google_calendar import open_google_calendar
from planner.llm import parser_lm
from planner.parser.parse import Parser


def make_calendar() -> CalendarBackend:
    if os.environ.get("PLANNER_CALENDAR", "fake") == "google":
        return open_google_calendar(get_credentials())
    return FakeCalendar(demo_events(date.today()))


WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"

load_dotenv()  # GOOGLE_API_KEY for Gemini
if not os.environ.get("GOOGLE_API_KEY"):
    # Fail at startup with a fix, not on the first chat message.
    raise SystemExit(
        "GOOGLE_API_KEY is not set: put it in .env (local) or pass it to the "
        "container (docker run -e GOOGLE_API_KEY=...)."
    )
app = create_app(
    PlannerTools(make_calendar(), Parser(parser_lm())),
    static_dir=WEB_DIST if WEB_DIST.is_dir() else None,
)
