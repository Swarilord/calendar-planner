"""Manual live check against the real Google Calendar (never run by the tests).

    uv run python -m planner.calendar.auth     # once: log in in the browser
    uv run python -m experiments.calendar_live

Reads this week's busy events, writes one 30-minute test block into the
"Study plan" calendar, applies it a second time (must write nothing), then
deletes it again. Only the app's own calendar is ever written to.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from planner.calendar.apply import apply_plan
from planner.calendar.auth import get_credentials
from planner.calendar.google_calendar import open_google_calendar
from planner.schedule import Schedule, ScheduledBlock

ZURICH = ZoneInfo("Europe/Zurich")


def main() -> None:
    google = open_google_calendar(get_credentials())
    print(f"Reading {len(google.read_ids)} calendars; writing only to Study plan.")

    now = datetime.now(UTC)
    events = google.list_events(now, now + timedelta(days=7))
    print(f"\nBusy in the next 7 days: {len(events)} events")
    for e in events[:10]:
        mark = " (ours)" if e.created_by_planner else ""
        print(f"  {e.start.astimezone(ZURICH):%a %d %b %H:%M}  {e.title}{mark}")

    start = (now + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    block = ScheduledBlock(
        task_name="Planner live test", start=start, end=start + timedelta(minutes=30)
    )
    schedule = Schedule(blocks=[block])

    first = apply_plan(google, "live-test", schedule)
    print(f"\nApply 1: created {len(first.created)}, conflicts {len(first.conflicts)}")
    second = apply_plan(google, "live-test", schedule)
    print(
        f"Apply 2: created {len(second.created)}, already there {second.already_there}"
    )

    for event in first.created:
        google.delete_event(event.id)
    print("Test block deleted again.")


if __name__ == "__main__":
    main()
