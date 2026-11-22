"""In-memory calendar for tests and evals. Never touches the real Google Calendar."""

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter

from planner.calendar.backend import EventNotFoundError, NotOwnedError
from planner.calendar.models import Event, EventChanges, NewEvent

_EVENT_LIST = TypeAdapter(list[Event])


class FakeCalendar:
    """A CalendarBackend that keeps events in a dict.

    Ids are "fake-1", "fake-2", ... so test results are the same on every run.
    """

    def __init__(self, events: Iterable[Event] = ()) -> None:
        self._events: dict[str, Event] = {}
        for event in events:
            if event.id in self._events:
                raise ValueError(f"duplicate event id: {event.id}")
            self._events[event.id] = event
        self._next_id = 1

    @classmethod
    def from_json(cls, path: Path) -> "FakeCalendar":
        """Load events from a JSON file containing a list of events."""
        return cls(_EVENT_LIST.validate_json(path.read_bytes()))

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        # Half-open overlap: an event ending exactly at `start` is not included.
        found = [e for e in self._events.values() if e.start < end and e.end > start]
        return sorted(found, key=lambda e: e.start)

    def create_event(self, event: NewEvent) -> Event:
        event_id = self._new_id()
        created = Event(**event.model_dump(), id=event_id, created_by_planner=True)
        self._events[event_id] = created
        return created

    def update_event(self, event_id: str, changes: EventChanges) -> Event:
        old = self._owned_event(event_id)
        # Build a new Event from old fields + changes so all checks run again
        # (e.g. end after start). None in changes means "leave as it is".
        merged = old.model_dump() | changes.model_dump(exclude_none=True)
        updated = Event.model_validate(merged)
        self._events[event_id] = updated
        return updated

    def delete_event(self, event_id: str) -> None:
        self._owned_event(event_id)
        del self._events[event_id]

    def _owned_event(self, event_id: str) -> Event:
        event = self._events.get(event_id)
        if event is None:
            raise EventNotFoundError(event_id)
        if not event.created_by_planner:
            raise NotOwnedError(event_id)
        return event

    def _new_id(self) -> str:
        while f"fake-{self._next_id}" in self._events:
            self._next_id += 1
        event_id = f"fake-{self._next_id}"
        self._next_id += 1
        return event_id
