"""Tests for GoogleCalendar with scripted HTTP responses: no network, no Google.

The client library ships Google's API description (static discovery), so a fake
HTTP object is all it needs. HttpMockSequence returns the scripted responses in
order and records every request, so tests can check what we sent.
"""

import json
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo

import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.http import HttpMockSequence

from planner.calendar.apply import apply_plan
from planner.calendar.auth import LoginRequiredError
from planner.calendar.backend import CalendarBackend, EventNotFoundError, NotOwnedError
from planner.calendar.google_calendar import MARKER, STUDY_CALENDAR, GoogleCalendar
from planner.calendar.models import EventChanges, NewEvent
from planner.schedule import Schedule, ScheduledBlock

Z = ZoneInfo("Europe/Zurich")
START, END = datetime(2026, 11, 23, tzinfo=Z), datetime(2026, 11, 30, tzinfo=Z)
OK = {"status": "200"}
STUDY = "study@group.calendar.google.com"


def z(day: int, hour: int) -> datetime:
    return datetime(2026, 11, day, hour, tzinfo=Z)


def item(event_id: str, start: datetime, end: datetime, **extra: Any) -> dict[str, Any]:
    """An event as Google's JSON."""
    return {
        "id": event_id,
        "summary": event_id,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        **extra,
    }


def service_on(http: Any) -> Any:
    """The Calendar API client on a fake HTTP object. (The type stubs only allow
    HttpMock here; the library accepts any object with a request() method.)"""
    return build("calendar", "v3", http=http, static_discovery=True)


OURS = {"extendedProperties": {"private": {"created_by": "planner", "plan_id": "p1"}}}


def calendar(*responses: tuple[dict[str, str], Any]) -> tuple[GoogleCalendar, Any]:
    """A GoogleCalendar on scripted responses (reading: study calendar only)."""
    http = HttpMockSequence(
        [(h, b if isinstance(b, str) else json.dumps(b)) for h, b in responses]
    )
    service = service_on(http)
    return GoogleCalendar(service, STUDY, [STUDY]), http


def sent(http: Any, index: int) -> tuple[str, str, Any]:
    """(method, path, json body) of the index-th request."""
    uri, method, body, _ = http.request_sequence[index]
    path = unquote(urlparse(uri).path)  # calendar ids are URL-encoded (@ -> %40)
    return method, path, json.loads(body) if body else None


def query(http: Any, index: int) -> dict[str, list[str]]:
    return parse_qs(urlparse(http.request_sequence[index][0]).query)


# --- connect: finding or creating the Study plan calendar ---


def connect(*responses: tuple[dict[str, str], Any]) -> tuple[GoogleCalendar, Any]:
    http = HttpMockSequence([(h, json.dumps(b)) for h, b in responses])
    service = service_on(http)
    return GoogleCalendar.connect(service), http


def test_connect_finds_our_calendar_and_the_shown_ones() -> None:
    entries = [
        {"id": "primary@x", "summary": "Me", "selected": True},
        {"id": "eth@x", "summary": "ETH timetable", "selected": True},
        {"id": "hidden@x", "summary": "Birthdays", "selected": False},
        {"id": STUDY, "summary": STUDY_CALENDAR, "description": MARKER},
    ]
    google, _ = connect((OK, {"items": entries}))
    assert google.study_id == STUDY
    assert google.read_ids == [STUDY, "primary@x", "eth@x"]  # hidden one skipped


def test_connect_creates_the_calendar_once_and_ignores_a_namesake() -> None:
    # The user has their own "Study plan" without our marker: not ours.
    namesake = {"id": "users@x", "summary": STUDY_CALENDAR, "selected": True}
    google, http = connect((OK, {"items": [namesake]}), (OK, {"id": "new@x"}))
    method, path, body = sent(http, 1)
    assert (method, path) == ("POST", "/calendar/v3/calendars")
    assert body["summary"] == STUDY_CALENDAR and body["description"] == MARKER
    assert google.study_id == "new@x"
    assert google.read_ids == ["new@x", "users@x"]  # still busy time to respect


# --- list_events ---


def test_list_events_reads_timed_busy_events_across_pages() -> None:
    page1 = {
        "items": [
            item("lecture", z(24, 10), z(24, 12)),
            item("birthday", z(24, 0), z(25, 0)) | {"start": {"date": "2026-11-24"}},
            item("free", z(24, 13), z(24, 14), transparency="transparent"),
        ],
        "nextPageToken": "more",
    }
    page2 = {
        "items": [
            item("gone", z(25, 9), z(25, 10), status="cancelled"),
            item(
                "declined",
                z(25, 11),
                z(25, 12),
                attendees=[{"self": True, "responseStatus": "declined"}],
            ),
            item("block", z(25, 14), z(25, 16), **OURS),
        ]
    }
    google, http = calendar((OK, page1), (OK, page2))
    events = google.list_events(START, END)

    assert [e.id for e in events] == ["lecture", "block"]
    assert events[1].created_by_planner and events[1].plan_id == "p1"
    assert not events[0].created_by_planner
    first = query(http, 0)
    assert first["timeMin"] == [START.isoformat()] and first["singleEvents"] == ["true"]
    assert query(http, 1)["pageToken"] == ["more"]


def test_tag_counts_only_in_our_own_calendar() -> None:
    # A copy of a tagged event in another calendar must not become editable.
    other = {"items": [item("copy", z(24, 14), z(24, 15), **OURS)]}
    google, _ = calendar((OK, other))
    google.read_ids = ["primary@x"]
    assert not google.list_events(START, END)[0].created_by_planner


# --- writing ---


def test_create_event_writes_tags_into_our_calendar() -> None:
    reply = item("new1", z(24, 14), z(24, 16), **OURS)
    google, http = calendar((OK, reply))
    event = google.create_event(
        NewEvent(title="Analysis", start=z(24, 14), end=z(24, 16), plan_id="p1")
    )
    method, path, body = sent(http, 0)
    assert (method, path) == ("POST", f"/calendar/v3/calendars/{STUDY}/events")
    assert body["extendedProperties"]["private"] == {
        "created_by": "planner",
        "plan_id": "p1",
    }
    assert event.created_by_planner and event.id == "new1"


def test_untagged_event_is_never_deleted() -> None:
    google, http = calendar((OK, item("mine", z(24, 14), z(24, 15))))
    with pytest.raises(NotOwnedError):
        google.delete_event("mine")
    assert len(http.request_sequence) == 1  # only the GET, no DELETE was sent


def test_tagged_event_is_deleted() -> None:
    google, http = calendar((OK, item("b", z(24, 14), z(24, 15), **OURS)), (OK, ""))
    google.delete_event("b")
    assert sent(http, 1)[:2] == ("DELETE", f"/calendar/v3/calendars/{STUDY}/events/b")


def test_missing_event_is_reported() -> None:
    google, _ = calendar(({"status": "404"}, {"error": {"code": 404}}))
    with pytest.raises(EventNotFoundError):
        google.delete_event("nope")


def test_update_patches_and_validates() -> None:
    old = item("b", z(24, 14), z(24, 15), **OURS)
    new = item("b", z(24, 16), z(24, 17), **OURS)
    google, http = calendar((OK, old), (OK, new))
    event = google.update_event("b", EventChanges(start=z(24, 16), end=z(24, 17)))
    assert sent(http, 1)[0] == "PATCH"
    assert event.start == z(24, 16)


# --- errors ---


def test_rate_limit_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("googleapiclient.http.time.sleep", lambda seconds: None)
    google, http = calendar(({"status": "429"}, "{}"), (OK, {"items": []}))
    assert google.list_events(START, END) == []
    assert len(http.request_sequence) == 2  # tried again after the 429


def test_expired_login_becomes_login_required() -> None:
    class ExpiredHttp(HttpMockSequence):
        def request(self, *args: Any, **kwargs: Any) -> Any:
            raise RefreshError("invalid_grant")

    service = service_on(ExpiredHttp([]))
    with pytest.raises(LoginRequiredError, match="planner.calendar.auth"):
        GoogleCalendar(service, STUDY, [STUDY]).list_events(START, END)


# --- together with apply_plan ---


def test_apply_plan_works_on_google_calendar() -> None:
    schedule = Schedule(
        blocks=[ScheduledBlock(task_name="Analysis", start=z(24, 14), end=z(24, 16))]
    )
    created = item("new1", z(24, 14), z(24, 16), summary="Analysis", **OURS)
    google, http = calendar((OK, {"items": []}), (OK, created))
    backend: CalendarBackend = google  # mypy checks it fits the interface
    assert len(apply_plan(backend, "p1", schedule).created) == 1

    # Applying again: the list now contains our event, so nothing is written.
    google, http = calendar((OK, {"items": [created]}))
    result = apply_plan(google, "p1", schedule)
    assert result.already_there == 1 and len(http.request_sequence) == 1
