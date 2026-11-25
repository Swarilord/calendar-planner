"""Runnable demo: the planner agent on a fake calendar with lectures.

Uses the real Gemini (GOOGLE_API_KEY from .env) but never a real calendar.
Run:  uv run python -m experiments.planner_agent.chat
  or  uv run adk run experiments/planner_agent
"""

from datetime import date

from dotenv import load_dotenv

from planner.agent.agent import build_agent
from planner.agent.tools import PlannerTools
from planner.calendar.demo import demo_events
from planner.calendar.fake import FakeCalendar
from planner.llm import parser_lm
from planner.parser.parse import Parser

load_dotenv()  # GOOGLE_API_KEY from the repo's .env
calendar = FakeCalendar(demo_events(date.today()))
root_agent = build_agent(PlannerTools(calendar, Parser(parser_lm())))
