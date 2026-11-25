"""Tests for applying a confirmed plan: idempotent, and safe against new clashes."""

from datetime import datetime
from zoneinfo import ZoneInfo

from planner.calendar.apply import apply_plan
from planner.calendar.fake import FakeCalendar
from planner.calendar.models import Event, NewEvent
from planner.schedule import Schedule, ScheduledBlock

Z = ZoneInfo("Europe/Zurich")


def z(day: int, hour: int) -> datetime:
    return datetime(2026, 11, day, hour, tzinfo=Z)


SCHEDULE = Schedule(
    blocks=[
        ScheduledBlock(task_name="Analysis", start=z(24, 14), end=z(24, 16)),
        ScheduledBlock(task_name="Analysis", start=z(25, 8), end=z(25, 10)),
    ]
)
LECTURE = Event(id="lec", title="Lecture", start=z(24, 10), end=z(24, 12))


def everything(calendar: FakeCalendar) -> list[Event]:
    return calendar.list_events(z(23, 0), z(30, 0))


def test_apply_creates_tagged_events() -> None:
    calendar = FakeCalendar([LECTURE])
    result = apply_plan(calendar, "plan-1", SCHEDULE)
    assert result.ok and len(result.created) == 2 and result.already_there == 0
    assert all(e.created_by_planner and e.plan_id == "plan-1" for e in result.created)


def test_applying_twice_gives_the_same_calendar() -> None:
    calendar = FakeCalendar([LECTURE])
    apply_plan(calendar, "plan-1", SCHEDULE)
    once = everything(calendar)
    second = apply_plan(calendar, "plan-1", SCHEDULE)  # double click on Confirm
    assert second.created == [] and second.already_there == 2
    assert everything(calendar) == once


def test_apply_after_a_crash_adds_only_the_missing_block() -> None:
    calendar = FakeCalendar()
    first = SCHEDULE.blocks[0]
    calendar.create_event(  # the first block was written before the crash
        NewEvent(title=first.task_name, start=first.start, end=first.end)
    )
    result = apply_plan(calendar, "plan-1", SCHEDULE)
    assert [e.start for e in result.created] == [SCHEDULE.blocks[1].start]
    assert result.already_there == 1
    assert len(everything(calendar)) == 2


def test_new_clash_since_the_preview_writes_nothing() -> None:
    meeting = Event(id="m", title="Meeting", start=z(25, 9), end=z(25, 11))
    calendar = FakeCalendar([LECTURE, meeting])  # added after the preview
    result = apply_plan(calendar, "plan-1", SCHEDULE)
    assert not result.ok and result.conflicts == [meeting]
    assert result.created == []
    assert everything(calendar) == [LECTURE, meeting]  # not even the first block


def test_a_user_event_with_the_same_time_and_title_is_not_ours() -> None:
    # Same title and time, but the user made it: still a clash, not a duplicate.
    mine = Event(id="u", title="Analysis", start=z(24, 14), end=z(24, 16))
    result = apply_plan(FakeCalendar([mine]), "plan-1", SCHEDULE)
    assert result.conflicts == [mine]


def test_empty_schedule_does_nothing() -> None:
    assert apply_plan(FakeCalendar(), "plan-1", Schedule()).created == []
