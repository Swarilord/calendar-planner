"""Runnable demo: the planner agent on a fake calendar with lectures.

Uses the real Gemini (GOOGLE_API_KEY from .env) but never a real calendar.
Run:  uv run python -m experiments.planner_agent.chat
  or  uv run adk run experiments/planner_agent
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from planner.agent.agent import build_agent
from planner.agent.tools import PlannerTools
from planner.calendar.fake import FakeCalendar
from planner.calendar.models import Event
from planner.llm import parser_lm
from planner.parser.parse import Parser

ZURICH = ZoneInfo("Europe/Zurich")

# (weekday 0=Mon, title, start, end), repeated this week and next week.
WEEKLY = [
    (0, "Analysis lecture", time(10, 15), time(12, 0)),
    (1, "Linear Algebra lecture", time(13, 15), time(15, 0)),
    (2, "Analysis lecture", time(10, 15), time(12, 0)),
    (3, "Linear Algebra lecture", time(13, 15), time(15, 0)),
    (3, "Exercise class", time(17, 0), time(18, 0)),
    (4, "Analysis lecture", time(10, 15), time(12, 0)),
]


def demo_events(today: date) -> list[Event]:
    monday = today - timedelta(days=today.weekday())
    events: list[Event] = []
    for week in (0, 1):
        for weekday, title, start, end in WEEKLY:
            day = monday + timedelta(days=7 * week + weekday)
            events.append(
                Event(
                    id=f"demo-{len(events) + 1}",
                    title=title,
                    start=datetime.combine(day, start, tzinfo=ZURICH),
                    end=datetime.combine(day, end, tzinfo=ZURICH),
                )
            )
    return events


load_dotenv()  # GOOGLE_API_KEY from the repo's .env
calendar = FakeCalendar(demo_events(date.today()))
root_agent = build_agent(PlannerTools(calendar, Parser(parser_lm())))
