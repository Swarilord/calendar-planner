"""Agent tools: plain Python functions the conversation agent can call.

There is no LLM logic here. ADK (step 4.3) lets Gemini decide when to call
them; each one reads the calendar and/or runs parser -> solver -> checker and
returns a small dict with a `status` field. No tool writes to the calendar:
plans stay drafts until the user confirms in the UI (Phase 8).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from planner.calendar.backend import CalendarBackend
from planner.calendar.models import Event
from planner.checker.check import check
from planner.parser.parse import ParseResult, ParserUnavailableError
from planner.parser.schemas import PlanRequest
from planner.schedule import ScheduledBlock
from planner.solver.model import SolveResult, SolveStatus, solve

TIMEZONE = "Europe/Zurich"
SUMMARY_DAYS = 7  # how far ahead the parser sees existing events
MAX_EVENTS = 50  # keep tool outputs small, so the agent's context stays small

Result = dict[str, Any]


class RequestParser(Protocol):
    """Anything that turns text into a ParseResult (the DSPy Parser, or a fake).
    Raises ParserUnavailableError if the LM behind it does not answer."""

    def parse(
        self, text: str, now: datetime, calendar_summary: str = ""
    ) -> ParseResult: ...


@dataclass(frozen=True)
class Draft:
    """A proposed plan, kept until the user confirms or revises it."""

    plan_id: str
    text: str  # the request text it was made from
    request: PlanRequest
    result: SolveResult


class PlannerTools:
    def __init__(
        self,
        calendar: CalendarBackend,
        parser: RequestParser,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.calendar = calendar
        self.parser = parser
        self.clock = clock
        self.tz = ZoneInfo(TIMEZONE)
        self.drafts: dict[str, Draft] = {}

    # --- read-only tools ---

    def get_now(self) -> Result:
        """Current date, time and timezone. Call before reading relative dates."""
        now = self.clock().astimezone(self.tz)
        return {
            "status": "ok",
            "now": now.isoformat(timespec="minutes"),
            "weekday": f"{now:%A}",
            "timezone": TIMEZONE,
        }

    def get_events(self, start: str, end: str) -> Result:
        """Events between start and end (ISO 8601 with offset), in Zurich time."""
        try:
            start_dt, end_dt = _parse_range(start, end)
        except ValueError as error:
            return _error(str(error))
        events = self.calendar.list_events(start_dt, end_dt)
        return {
            "status": "ok",
            "events": [
                {"title": e.title, **self._span(e.start, e.end)}
                for e in events[:MAX_EVENTS]
            ],
            "truncated": len(events) > MAX_EVENTS,
        }

    def get_free_slots(self, start: str, end: str, min_minutes: int = 30) -> Result:
        """Free windows of at least min_minutes between start and end."""
        try:
            start_dt, end_dt = _parse_range(start, end)
        except ValueError as error:
            return _error(str(error))
        if min_minutes <= 0:
            return _error("min_minutes must be positive")
        events = self.calendar.list_events(start_dt, end_dt)
        slots = _free_windows(start_dt, end_dt, events)
        long_enough = [
            (s, e) for s, e in slots if e - s >= timedelta(minutes=min_minutes)
        ]
        return {
            "status": "ok",
            "free": [
                {**self._span(s, e), "minutes": int((e - s).total_seconds() // 60)}
                for s, e in long_enough[:MAX_EVENTS]
            ],
        }

    # --- planning tools (they store drafts, never write to the calendar) ---

    def propose_plan(self, request_text: str) -> Result:
        """Parse the request, schedule it and store the result as a draft plan."""
        return self._plan(request_text)

    def revise_plan(self, plan_id: str, change_text: str) -> Result:
        """Plan again from an earlier draft's request plus a change."""
        draft = self.drafts.get(plan_id)
        if draft is None:
            return _error(f"unknown plan_id {plan_id!r}")
        return self._plan(f"{draft.text}\nChange: {change_text}")

    def explain_infeasible(self, plan_id: str) -> Result:
        """The rules that make a draft impossible, in words."""
        draft = self.drafts.get(plan_id)
        if draft is None:
            return _error(f"unknown plan_id {plan_id!r}")
        if draft.result.status != SolveStatus.INFEASIBLE:
            return {"status": "ok", "infeasible": False, "reasons": []}
        return {
            "status": "ok",
            "infeasible": True,
            "reasons": _reasons(draft.result),
        }

    def _plan(self, text: str) -> Result:
        now = self.clock()
        upcoming = self.calendar.list_events(now, now + timedelta(days=SUMMARY_DAYS))
        try:
            parsed = self.parser.parse(text, now, self.summarize(upcoming))
        except ParserUnavailableError:
            return {
                "status": "unavailable",
                "message": "The planning service (Gemini) did not answer. "
                "Ask the user to try again in a minute.",
            }
        if parsed.request is None:
            return {
                "status": "error",
                "message": "Could not turn the request into a plan. "
                "Ask the user to clarify.",
                "details": parsed.errors,
            }

        request = parsed.request
        events = self.calendar.list_events(request.horizon_start, request.horizon_end)
        result = solve(request, events)
        plan_id = f"plan-{len(self.drafts) + 1}"
        self.drafts[plan_id] = Draft(plan_id, text, request, result)

        if result.status == SolveStatus.INFEASIBLE:
            return {
                "status": "infeasible",
                "plan_id": plan_id,
                "reasons": _reasons(result),
            }
        if result.schedule is None:  # TIMED_OUT
            return _error("The solver ran out of time; try a shorter horizon.")

        # The independent referee: a solver bug must never reach the user.
        violations = check(request, events, result.schedule)
        if violations:
            return {
                "status": "error",
                "message": "Internal error: the plan broke a rule.",
                "details": [v.message for v in violations],
            }
        return {
            "status": "ok",
            "plan_id": plan_id,
            "proven_best": result.status == SolveStatus.OPTIMAL,
            "blocks": [self._block(b) for b in result.schedule.blocks],
        }

    # --- formatting: UTC inside, Zurich time in everything the agent sees ---

    def summarize(self, events: Sequence[Event]) -> str:
        """One line per event, e.g. 'Mon 23 Nov 09:00-11:00 Lecture'."""
        if not events:
            return "(no events)"
        return "\n".join(
            f"{self._local(e.start)}-{self._clock(e.start, e.end)} {e.title}"
            for e in events[:MAX_EVENTS]
        )

    def _block(self, block: ScheduledBlock) -> Result:
        return {"task": block.task_name, **self._span(block.start, block.end)}

    def _span(self, start: datetime, end: datetime) -> dict[str, str]:
        return {"start": self._local(start), "end": self._clock(start, end)}

    def _local(self, moment: datetime) -> str:
        return f"{moment.astimezone(self.tz):%a %d %b %H:%M}"

    def _clock(self, start: datetime, end: datetime) -> str:
        """End time alone if on the same local day, else with the date."""
        same_day = start.astimezone(self.tz).date() == end.astimezone(self.tz).date()
        return f"{end.astimezone(self.tz):%H:%M}" if same_day else self._local(end)


def _parse_range(start: str, end: str) -> tuple[datetime, datetime]:
    start_dt, end_dt = _parse_time(start), _parse_time(end)
    if end_dt <= start_dt:
        raise ValueError("end must be after start")
    return start_dt, end_dt


def _parse_time(text: str) -> datetime:
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"not an ISO 8601 time: {text!r}") from None
    if moment.tzinfo is None:
        raise ValueError(
            f"{text!r} has no UTC offset; write e.g. 2026-11-24T09:00+01:00"
        )
    return moment.astimezone(UTC)


def _free_windows(
    start: datetime, end: datetime, events: Sequence[Event]
) -> list[tuple[datetime, datetime]]:
    """Gaps between events inside [start, end). Events may overlap each other."""
    windows = []
    cursor = start
    for event in sorted(events, key=lambda e: e.start):
        if event.start > cursor:
            windows.append((cursor, min(event.start, end)))
        cursor = max(cursor, event.end)
    if cursor < end:
        windows.append((cursor, end))
    return windows


def _reasons(result: SolveResult) -> list[str]:
    if not result.conflicts:
        return ["There is not enough free time in the calendar for this request."]
    return [conflict.description for conflict in result.conflicts]


def _error(message: str) -> Result:
    return {"status": "error", "message": message}
