"""GoogleCalendar: the CalendarBackend for the real Google Calendar (API v3).

Reads busy time from every calendar the user shows in Google Calendar, and
writes only to the app's own "Study plan" calendar. Google enforces that too:
the calendar.app.created scope cannot write anywhere else. On top of that, the
app changes only events tagged created_by=planner (private extended property).

The API client is untyped here (Any): the service object is built from Google's
discovery document at run time.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from planner.calendar.auth import LoginRequiredError
from planner.calendar.backend import CalendarError, EventNotFoundError, NotOwnedError
from planner.calendar.models import Event, EventChanges, NewEvent

STUDY_CALENDAR = "Study plan"
# In the calendar's description: a calendar the user named "Study plan" is not ours.
MARKER = "Created by calendar-planner. created_by=planner"
TAG = ("created_by", "planner")
TIMEZONE = "Europe/Zurich"
RETRIES = 5  # the client retries 429, 5xx and 403 rate limits with backoff
PAGE_SIZE = 2500  # the API's maximum


class GoogleCalendar:
    """A CalendarBackend backed by Google Calendar."""

    def __init__(self, service: Any, study_id: str, read_ids: list[str]) -> None:
        self.service = service
        self.study_id = study_id  # the only calendar we write to
        self.read_ids = read_ids  # calendars whose events count as busy

    @classmethod
    def connect(cls, service: Any) -> "GoogleCalendar":
        """Find the Study plan calendar (create it if missing) and the calendars
        to read: those the user shows in Google Calendar ("selected")."""
        entries = _all_pages(lambda token: service.calendarList().list(pageToken=token))
        ours = [
            e
            for e in entries
            if e.get("summary") == STUDY_CALENDAR and e.get("description") == MARKER
        ]
        if ours:
            study_id = ours[0]["id"]
        else:
            body = {
                "summary": STUDY_CALENDAR,
                "description": MARKER,
                "timeZone": TIMEZONE,
            }
            study_id = _run(service.calendars().insert(body=body))["id"]
        shown = [e["id"] for e in entries if e.get("selected") and e["id"] != study_id]
        return cls(service, study_id, [study_id, *shown])

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        found: dict[str, Event] = {}
        for calendar_id in self.read_ids:

            def page(token: str | None, calendar_id: str = calendar_id) -> Any:
                return self.service.events().list(
                    calendarId=calendar_id,
                    # The API filters by end > timeMin and start < timeMax:
                    # exactly our half-open overlap rule.
                    timeMin=start.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,  # one item per occurrence of a series
                    maxResults=PAGE_SIZE,
                    pageToken=token,
                )

            for item in _all_pages(page):
                event = self._to_event(item, calendar_id)
                # One meeting can appear in two calendars with the same id.
                if event is not None and event.id not in found:
                    found[event.id] = event
        return sorted(found.values(), key=lambda e: e.start)

    def create_event(self, event: NewEvent) -> Event:
        tags = {TAG[0]: TAG[1]}
        if event.plan_id is not None:
            tags["plan_id"] = event.plan_id
        body = {
            "summary": event.title,
            "start": {"dateTime": event.start.isoformat()},
            "end": {"dateTime": event.end.isoformat()},
            "extendedProperties": {"private": tags},
        }
        item = _run(self.service.events().insert(calendarId=self.study_id, body=body))
        created = self._to_event(item, self.study_id)
        if created is None:
            raise CalendarError("Google returned an unexpected event")
        return created

    def update_event(self, event_id: str, changes: EventChanges) -> Event:
        old = self._owned(event_id)
        # Merge and validate first (e.g. end after start), as FakeCalendar does.
        merged = Event.model_validate(
            old.model_dump() | changes.model_dump(exclude_none=True)
        )
        body = {
            "summary": merged.title,
            "start": {"dateTime": merged.start.isoformat()},
            "end": {"dateTime": merged.end.isoformat()},
        }
        item = _run(
            self.service.events().patch(
                calendarId=self.study_id, eventId=event_id, body=body
            )
        )
        updated = self._to_event(item, self.study_id)
        if updated is None:
            raise CalendarError("Google returned an unexpected event")
        return updated

    def delete_event(self, event_id: str) -> None:
        self._owned(event_id)
        _run(self.service.events().delete(calendarId=self.study_id, eventId=event_id))

    def _owned(self, event_id: str) -> Event:
        """The event, if it is in our calendar and carries our tag."""
        item = _run(
            self.service.events().get(calendarId=self.study_id, eventId=event_id)
        )
        event = self._to_event(item, self.study_id)
        if event is None:
            raise EventNotFoundError(event_id)  # cancelled, or not a timed event
        if not event.created_by_planner:
            raise NotOwnedError(event_id)
        return event

    def _to_event(self, item: dict[str, Any], calendar_id: str) -> Event | None:
        """Google's JSON -> our Event; None for events that don't block time."""
        start = item.get("start", {}).get("dateTime")
        end = item.get("end", {}).get("dateTime")
        if (
            start is None  # all-day event (birthday, holiday): has "date" only
            or end is None
            or item.get("status") == "cancelled"
            or item.get("transparency") == "transparent"  # shown as "free"
            or _declined(item)
        ):
            return None
        tags = item.get("extendedProperties", {}).get("private", {})
        return Event(
            id=item["id"],
            title=item.get("summary") or "(no title)",
            start=datetime.fromisoformat(start),
            end=datetime.fromisoformat(end),
            plan_id=tags.get("plan_id"),
            created_by_planner=(
                calendar_id == self.study_id and tags.get(TAG[0]) == TAG[1]
            ),
        )


def open_google_calendar(creds: Credentials) -> GoogleCalendar:
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return GoogleCalendar.connect(service)


def _declined(item: dict[str, Any]) -> bool:
    """True if the user declined this invitation."""
    return any(
        a.get("self") and a.get("responseStatus") == "declined"
        for a in item.get("attendees", [])
    )


def _run(request: Any) -> Any:
    """Execute one API request with retries; translate errors into ours."""
    try:
        return request.execute(num_retries=RETRIES)
    except RefreshError as error:  # refresh token expired or revoked
        raise LoginRequiredError(
            "Google login expired: run `uv run python -m planner.calendar.auth`."
        ) from error
    except HttpError as error:
        if error.status_code in (404, 410):  # 410: deleted
            raise EventNotFoundError(str(error.uri)) from error
        raise CalendarError(f"Google Calendar error {error.status_code}") from error


def _all_pages(make_request: Callable[[str | None], Any]) -> list[dict[str, Any]]:
    """Follow nextPageToken until every item has been read."""
    items: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        page = _run(make_request(token))
        items.extend(page.get("items", []))
        token = page.get("nextPageToken")
        if not token:
            return items
