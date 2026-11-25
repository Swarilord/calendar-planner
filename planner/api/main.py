"""Entry point for the web backend.

    uv run uvicorn planner.api.main:app --reload             # fake calendar
    PLANNER_CALENDAR=google uv run uvicorn planner.api.main:app

With PLANNER_CALENDAR=google, log in once first: uv run python -m planner.calendar.auth
"""

import os
from datetime import date

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


load_dotenv()  # GOOGLE_API_KEY for Gemini
app = create_app(PlannerTools(make_calendar(), Parser(parser_lm())))
