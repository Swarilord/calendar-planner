"""A minimal ADK agent with one tool, get_now().

Run from the repo root:  uv run adk run experiments/hello_agent
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from google.adk.agents.llm_agent import Agent

ZURICH = ZoneInfo("Europe/Zurich")


def describe_time(moment: datetime) -> dict[str, str]:
    """Format a timezone-aware moment in UTC and in Zurich local time."""
    if moment.tzinfo is None:
        raise ValueError("moment must be timezone-aware")
    local = moment.astimezone(ZURICH)
    return {
        "status": "success",
        "utc": moment.astimezone(UTC).isoformat(timespec="minutes"),
        "zurich": local.isoformat(timespec="minutes"),
        "weekday": local.strftime("%A"),
        "timezone_abbreviation": local.tzname() or "",
    }


def get_now() -> dict[str, str]:
    """Return the current date and time, in UTC and in Zurich local time.

    Use this whenever the user's question depends on today's date or the
    current time, for example "what day is it" or "how long until Friday".
    """
    return describe_time(datetime.now(UTC))


root_agent = Agent(
    model="gemini-flash-latest",
    name="hello_agent",
    description="Answers questions about the current date and time.",
    instruction=(
        "You are a helpful assistant for a student in Zurich. You do not know "
        "the current date or time yourself: call get_now whenever the answer "
        "depends on it. Answer in Zurich local time."
    ),
    tools=[get_now],
)
