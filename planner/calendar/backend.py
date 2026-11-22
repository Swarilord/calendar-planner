"""The interface every calendar implements, and the errors it may raise."""

from datetime import datetime
from typing import Protocol

from planner.calendar.models import Event, EventChanges, NewEvent


class CalendarError(Exception):
    """Base class for calendar errors."""


class EventNotFoundError(CalendarError):
    """No event with this id exists."""


class NotOwnedError(CalendarError):
    """The event was not created by this app, so it must not be changed."""


class CalendarBackend(Protocol):
    """Any calendar: FakeCalendar for tests and evals, GoogleCalendar for real use.

    Times are timezone-aware. Implementations must only update or delete events
    with created_by_planner=True, and raise NotOwnedError otherwise.
    """

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        """Events overlapping [start, end), sorted by start time."""
        ...

    def create_event(self, event: NewEvent) -> Event:
        """Create an event owned by this app and return it with its new id."""
        ...

    def update_event(self, event_id: str, changes: EventChanges) -> Event:
        """Apply changes to an event this app owns and return the new version."""
        ...

    def delete_event(self, event_id: str) -> None:
        """Delete an event this app owns."""
        ...
