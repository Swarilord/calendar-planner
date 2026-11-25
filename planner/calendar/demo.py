"""A demo week of lectures for the fake calendar (local runs and the web demo)."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from planner.calendar.models import Event

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
