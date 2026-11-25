"""Tests for the web backend: real HTTP requests through FastAPI's TestClient,
with the scripted Gemini, a fake parser and FakeCalendar. No network."""

from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import httpx
from fastapi.testclient import TestClient
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from planner.api.app import create_app
from planner.calendar.auth import LoginRequiredError
from planner.calendar.fake import FakeCalendar
from planner.calendar.models import NewEvent
from planner.parser.parse import ParseResult
from tests.test_agent import ScriptedGemini, call, say
from tests.test_agent_tools import LECTURE, LUNCH, make_tools, request, z

PLAN = [call("propose_plan", request_text="Analysis, 2h, today"), say("Draft ready.")]


def client(
    script: list[types.Content], result: ParseResult | None = None
) -> tuple[TestClient, FakeCalendar]:
    tools, _, calendar = make_tools(result)
    app = create_app(tools, ScriptedGemini(script=script))
    return TestClient(app), calendar


def planned(api: TestClient) -> dict[str, Any]:
    """Chat once (the agent proposes a plan) and return the draft."""
    plan_id = api.post("/api/chat", json={"message": "Analysis 2h"}).json()["plan_id"]
    return dict(api.get(f"/api/plans/{plan_id}").json())


# --- chat ---


def test_chat_returns_the_reply_and_the_new_plan() -> None:
    api, _ = client(PLAN)
    body = api.post("/api/chat", json={"message": "Analysis, 2h, today"}).json()
    assert body == {
        "reply": "Draft ready.",
        "tool_calls": ["propose_plan"],
        "plan_id": "plan-1",
    }


def test_chat_without_a_plan_has_no_plan_id() -> None:
    api, _ = client([say("Hi! What should I plan?")])
    assert api.post("/api/chat", json={"message": "hi"}).json()["plan_id"] is None


def test_empty_message_is_rejected_before_the_agent() -> None:
    api, _ = client([])
    assert api.post("/api/chat", json={"message": ""}).status_code == 422


def test_silent_gemini_is_503() -> None:
    class DownGemini(BaseLlm):
        model: str = "down"

        async def generate_content_async(
            self, llm_request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse]:
            raise httpx.ReadTimeout("no answer")
            yield  # makes this an async generator, like the real method

    tools, _, _ = make_tools()
    api = TestClient(create_app(tools, DownGemini()))
    response = api.post("/api/chat", json={"message": "plan"})
    assert response.status_code == 503 and "try again" in response.json()["detail"]


# --- plans ---


def test_plan_shows_proposed_blocks_and_existing_events() -> None:
    api, _ = client(PLAN)
    plan = planned(api)
    assert plan["status"] == "draft" and plan["reasons"] == []
    minutes = sum(
        (datetime.fromisoformat(b["end"]) - datetime.fromisoformat(b["start"])).seconds
        for b in plan["blocks"]
    )
    assert minutes == 120 * 60
    assert [(e["title"], e["mine"]) for e in plan["events"]] == [
        (LECTURE.title, False),
        (LUNCH.title, False),
    ]


def test_infeasible_plan_has_reasons_and_cannot_be_applied() -> None:
    api, _ = client(PLAN, ParseResult(request(600, z(24, 12))))  # 10h by noon
    plan = planned(api)
    assert plan["status"] == "infeasible" and plan["blocks"] == []
    assert plan["reasons"]
    assert api.post("/api/plans/plan-1/apply").status_code == 409


def test_unknown_plan_is_404() -> None:
    api, _ = client([])
    assert api.get("/api/plans/plan-9").status_code == 404
    assert api.post("/api/plans/plan-9/apply").status_code == 404


# --- confirm and reject ---


def test_confirm_writes_once_even_if_clicked_twice() -> None:
    api, calendar = client(PLAN)
    plan = planned(api)
    first = api.post("/api/plans/plan-1/apply").json()
    second = api.post("/api/plans/plan-1/apply").json()
    n = len(plan["blocks"])
    assert first == {"created": n, "already_there": 0}
    assert second == {"created": 0, "already_there": n}
    mine = [e for e in calendar.list_events(z(24, 0), z(25, 0)) if e.created_by_planner]
    assert len(mine) == n and all(e.plan_id == "plan-1" for e in mine)
    assert api.get("/api/plans/plan-1").json()["status"] == "applied"


def test_new_clash_since_the_preview_writes_nothing() -> None:
    api, calendar = client(PLAN)
    block = planned(api)["blocks"][0]
    calendar.create_event(  # a meeting booked after the user saw the preview
        NewEvent(title="Meeting", start=block["start"], end=block["end"])
    )
    response = api.post("/api/plans/plan-1/apply")
    assert response.status_code == 409 and "Meeting" in response.json()["detail"]
    titles = sorted(e.title for e in calendar.list_events(z(24, 0), z(25, 0)))
    assert titles == sorted([LECTURE.title, LUNCH.title, "Meeting"])  # no Analysis


def test_rejected_plan_cannot_be_applied() -> None:
    api, calendar = client(PLAN)
    planned(api)
    assert api.post("/api/plans/plan-1/reject").json()["status"] == "rejected"
    assert api.post("/api/plans/plan-1/apply").status_code == 409
    assert not any(
        e.created_by_planner for e in calendar.list_events(z(24, 0), z(25, 0))
    )


def test_expired_google_login_is_401() -> None:
    api, calendar = client(PLAN)
    planned(api)

    def expired(start: datetime, end: datetime) -> Any:
        raise LoginRequiredError("Google login needed: run the login command.")

    calendar.list_events = expired  # type: ignore[method-assign]
    response = api.get("/api/plans/plan-1")
    assert response.status_code == 401 and "login" in response.json()["detail"]
