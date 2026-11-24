"""Tests for the agent tools: FakeCalendar, a fake parser, a fixed clock. No LLM."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from planner.agent.tools import PlannerTools
from planner.calendar.fake import FakeCalendar
from planner.calendar.models import Event
from planner.parser.parse import ParseResult, ParserUnavailableError
from planner.parser.schemas import PlanRequest, Task
from planner.schedule import Schedule, ScheduledBlock
from planner.solver.model import SolveResult, SolveStatus

ZURICH = ZoneInfo("Europe/Zurich")


def z(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=ZURICH)


NOW = z(24, 8)  # Tuesday 24 Nov 2026, 08:00
LECTURE = Event(id="lecture", title="Lecture", start=z(24, 9), end=z(24, 11))
LUNCH = Event(id="lunch", title="Lunch", start=z(24, 12), end=z(24, 13))


class FakeParser:
    """Returns a fixed result and records what it was asked."""

    def __init__(self, result: ParseResult) -> None:
        self.result = result
        self.calls: list[tuple[str, datetime, str]] = []

    def parse(
        self, text: str, now: datetime, calendar_summary: str = ""
    ) -> ParseResult:
        self.calls.append((text, now, calendar_summary))
        return self.result


def request(minutes: int, deadline: datetime, **extra: object) -> PlanRequest:
    task = Task(name="Analysis", duration_min=minutes, deadline=deadline)
    return PlanRequest.model_validate(
        {"horizon_start": NOW, "horizon_end": z(25, 0), "tasks": [task], **extra}
    )


def make_tools(
    result: ParseResult | None = None, events: tuple[Event, ...] = (LECTURE, LUNCH)
) -> tuple[PlannerTools, FakeParser, FakeCalendar]:
    parser = FakeParser(result or ParseResult(request(120, z(24, 18))))
    calendar = FakeCalendar(events)
    return PlannerTools(calendar, parser, clock=lambda: NOW), parser, calendar


# --- read-only tools ---


def test_get_now_is_zurich_time_with_weekday() -> None:
    tools, _, _ = make_tools()
    assert tools.get_now() == {
        "status": "ok",
        "now": "2026-11-24T08:00+01:00",
        "weekday": "Tuesday",
        "timezone": "Europe/Zurich",
    }


def test_get_events_is_compact_and_local() -> None:
    tools, _, _ = make_tools()
    result = tools.get_events("2026-11-24T00:00+01:00", "2026-11-25T00:00+01:00")
    assert result["events"] == [
        {"title": "Lecture", "start": "Tue 24 Nov 09:00", "end": "11:00"},
        {"title": "Lunch", "start": "Tue 24 Nov 12:00", "end": "13:00"},
    ]


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("2026-11-24T09:00", "2026-11-24T10:00+01:00", "no UTC offset"),
        ("tomorrow", "2026-11-24T10:00+01:00", "not an ISO 8601 time"),
        ("2026-11-24T10:00+01:00", "2026-11-24T09:00+01:00", "end must be after"),
    ],
)
def test_bad_times_are_errors_the_agent_can_read(
    start: str, end: str, message: str
) -> None:
    tools, _, _ = make_tools()
    result = tools.get_events(start, end)
    assert result["status"] == "error"
    assert message in result["message"]


def test_free_slots_are_gaps_between_events() -> None:
    tools, _, _ = make_tools()
    result = tools.get_free_slots("2026-11-24T08:00+01:00", "2026-11-24T14:00+01:00")
    assert result["free"] == [
        {"start": "Tue 24 Nov 08:00", "end": "09:00", "minutes": 60},
        {"start": "Tue 24 Nov 11:00", "end": "12:00", "minutes": 60},
        {"start": "Tue 24 Nov 13:00", "end": "14:00", "minutes": 60},
    ]


def test_free_slots_merge_overlapping_events_and_skip_short_gaps() -> None:
    overlap = Event(id="o", title="Office hour", start=z(24, 10), end=z(24, 11, 45))
    tools, _, _ = make_tools(events=(LECTURE, overlap, LUNCH))
    result = tools.get_free_slots(
        "2026-11-24T08:00+01:00", "2026-11-24T14:00+01:00", min_minutes=30
    )
    # 11:45-12:00 is free but only 15 min long.
    assert [slot["start"] for slot in result["free"]] == [
        "Tue 24 Nov 08:00",
        "Tue 24 Nov 13:00",
    ]


# --- planning tools ---


def test_propose_plan_runs_parser_solver_and_checker() -> None:
    tools, parser, _ = make_tools()
    result = tools.propose_plan("Analysis, 2h, due today 18:00")
    assert result["status"] == "ok"
    assert result["plan_id"] == "plan-1"
    assert result["proven_best"] is True
    # Earlier is better: 1h before the lecture, 1h after lunch (11-12 is the
    # default lunch break, 12-13 is an event).
    assert result["blocks"] == [
        {"task": "Analysis", "start": "Tue 24 Nov 08:00", "end": "09:00"},
        {"task": "Analysis", "start": "Tue 24 Nov 13:00", "end": "14:00"},
    ]
    assert "plan-1" in tools.drafts


def test_parser_sees_now_and_upcoming_events() -> None:
    tools, parser, _ = make_tools()
    tools.propose_plan("Analysis, 2h")
    text, now, summary = parser.calls[0]
    assert now == NOW
    assert summary == "Tue 24 Nov 09:00-11:00 Lecture\nTue 24 Nov 12:00-13:00 Lunch"


def test_planning_never_writes_to_the_calendar() -> None:
    tools, _, calendar = make_tools()
    before = calendar.list_events(z(1, 0), z(30, 0))
    tools.propose_plan("Analysis, 2h")
    assert calendar.list_events(z(1, 0), z(30, 0)) == before


def test_unparseable_request_returns_the_reasons() -> None:
    failed = ParseResult(None, ["tasks.0.duration_min: must be a multiple of 15"])
    tools, _, _ = make_tools(failed)
    result = tools.propose_plan("Analysis, about 50 minutes")
    assert result["status"] == "error"
    assert result["details"] == ["tasks.0.duration_min: must be a multiple of 15"]
    assert tools.drafts == {}


def test_impossible_request_is_explained() -> None:
    # 20 h between 9 and 22 tomorrow: brief example 5.
    impossible = request(
        20 * 60, z(25, 0), day_start=time(9), day_end=time(22)
    ).model_copy(update={"horizon_start": z(24, 0)})
    tools, _, _ = make_tools(ParseResult(impossible), events=())
    result = tools.propose_plan("Fit 20 hours of revision into today")
    assert result == {
        "status": "infeasible",
        "plan_id": "plan-1",
        "reasons": ["work only between 09:00 and 22:00"],
    }
    assert tools.explain_infeasible("plan-1") == {
        "status": "ok",
        "infeasible": True,
        "reasons": ["work only between 09:00 and 22:00"],
    }


def test_explain_feasible_and_unknown_plans() -> None:
    tools, _, _ = make_tools()
    tools.propose_plan("Analysis, 2h")
    assert tools.explain_infeasible("plan-1")["infeasible"] is False
    assert tools.explain_infeasible("plan-9")["status"] == "error"


def test_revise_plan_replans_with_the_change_as_a_new_draft() -> None:
    tools, parser, _ = make_tools()
    tools.propose_plan("Analysis, 2h")
    result = tools.revise_plan("plan-1", "not after 16:00")
    assert result["plan_id"] == "plan-2"
    assert parser.calls[-1][0] == "Analysis, 2h\nChange: not after 16:00"
    assert set(tools.drafts) == {"plan-1", "plan-2"}  # the old draft is kept
    assert tools.revise_plan("plan-9", "x")["status"] == "error"


def test_checker_stops_a_broken_solver_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    # Swap in a "buggy solver" that books the block during the lecture.
    clash = Schedule(
        blocks=[ScheduledBlock(task_name="Analysis", start=z(24, 9), end=z(24, 11))]
    )
    monkeypatch.setattr(
        "planner.agent.tools.solve",
        lambda request, events: SolveResult(SolveStatus.OPTIMAL, clash),
    )
    tools, _, _ = make_tools()
    result = tools.propose_plan("Analysis, 2h")
    assert result["status"] == "error"
    assert any("clashes with event 'Lecture'" in d for d in result["details"])


def test_free_slots_with_an_event_inside_another() -> None:
    # A short meeting inside a long exam must not reopen the time after it.
    exam = Event(id="exam", title="Exam", start=z(24, 9), end=z(24, 12))
    inside = Event(id="m", title="Meeting", start=z(24, 10), end=z(24, 10, 30))
    tools, _, _ = make_tools(events=(exam, inside))
    result = tools.get_free_slots("2026-11-24T08:00+01:00", "2026-11-24T13:00+01:00")
    assert [(s["start"], s["end"]) for s in result["free"]] == [
        ("Tue 24 Nov 08:00", "09:00"),
        ("Tue 24 Nov 12:00", "13:00"),
    ]


def test_parser_outage_is_returned_not_raised() -> None:
    class DownParser:
        def parse(
            self, text: str, now: datetime, calendar_summary: str = ""
        ) -> ParseResult:
            raise ParserUnavailableError("gemini did not answer")

    tools = PlannerTools(FakeCalendar([LECTURE]), DownParser(), clock=lambda: NOW)
    result = tools.propose_plan("Analysis, 2h")
    assert result["status"] == "unavailable"
    assert "try again" in result["message"]
    assert tools.drafts == {}
