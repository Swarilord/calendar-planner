"""The web backend: a thin HTTP layer over the agent, the drafts and apply_plan.

Endpoints (all under /api):
    POST /chat               one message to the agent -> its reply (+ new plan_id)
    GET  /plans/{id}         a draft: proposed blocks plus the existing events
    POST /plans/{id}/apply   write it to the calendar (the Confirm button)
    POST /plans/{id}/reject  discard it (the Reject button)

The agent has no tool that writes to the calendar. Writing happens only in
/apply, which the user's Confirm click calls directly: the model has no path to it.
Single user, state in memory: a restart forgets drafts (applied plans are safe
in the calendar).
"""

from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import InMemoryRunner
from pydantic import BaseModel, Field

from planner.agent.agent import AgentUnavailableError, build_agent, run_turn
from planner.agent.tools import Draft, PlannerTools, reasons
from planner.calendar.apply import apply_plan
from planner.calendar.auth import LoginRequiredError
from planner.calendar.backend import CalendarError
from planner.calendar.models import Event
from planner.schedule import ScheduledBlock
from planner.solver.model import SolveStatus

APP_NAME, USER = "planner", "me"


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatOut(BaseModel):
    reply: str
    tool_calls: list[str]
    plan_id: str | None  # the draft made in this turn, if any


class EventOut(BaseModel):
    title: str
    start: datetime
    end: datetime
    mine: bool  # created by this app


class PlanOut(BaseModel):
    plan_id: str
    status: Literal["draft", "infeasible", "applied", "rejected"]
    blocks: list[ScheduledBlock]
    events: list[EventOut]  # what is already in the calendar
    reasons: list[str]  # why it is impossible (status "infeasible")


class ApplyOut(BaseModel):
    created: int
    already_there: int


def create_app(
    tools: PlannerTools,
    model: str | BaseLlm | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    """The FastAPI app around one PlannerTools (calendar + parser) and one chat."""
    app = FastAPI(title="Calendar planner")
    runner = InMemoryRunner(agent=build_agent(tools, model), app_name=APP_NAME)
    session_ids: list[str] = []  # the one chat session, created on first use
    status: dict[str, Literal["applied", "rejected"]] = {}

    @app.exception_handler(LoginRequiredError)
    async def login_required(
        request: Request, error: LoginRequiredError
    ) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": str(error)})

    @app.exception_handler(CalendarError)
    async def calendar_error(request: Request, error: CalendarError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(error)})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        """For Docker and Cloud Run: the server is up (no Gemini or Google call)."""
        return {"status": "ok"}

    @app.post("/api/chat")
    async def chat(body: ChatIn) -> ChatOut:
        if not session_ids:
            session = await runner.session_service.create_session(
                app_name=APP_NAME, user_id=USER
            )
            session_ids.append(session.id)
        before = set(tools.drafts)
        try:
            turn = await run_turn(runner, USER, session_ids[0], body.message)
        except AgentUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        new = [plan_id for plan_id in tools.drafts if plan_id not in before]
        return ChatOut(
            reply=turn.reply,
            tool_calls=turn.tool_calls,
            plan_id=new[-1] if new else None,
        )

    # Plain `def`: FastAPI runs these in a thread, so a slow Google call does
    # not block the server while it waits.
    @app.get("/api/plans/{plan_id}")
    def get_plan(plan_id: str) -> PlanOut:
        draft = _draft(tools, plan_id)
        request = draft.request
        events = tools.calendar.list_events(request.horizon_start, request.horizon_end)
        infeasible = draft.result.status == SolveStatus.INFEASIBLE
        schedule = draft.result.schedule
        return PlanOut(
            plan_id=plan_id,
            status=status.get(plan_id, "infeasible" if infeasible else "draft"),
            blocks=schedule.blocks if schedule else [],
            events=[_event_out(e) for e in events],
            reasons=reasons(draft.result) if infeasible else [],
        )

    @app.post("/api/plans/{plan_id}/apply")
    def apply(plan_id: str) -> ApplyOut:
        draft = _draft(tools, plan_id)
        if status.get(plan_id) == "rejected":
            raise HTTPException(status_code=409, detail="This plan was rejected.")
        if draft.result.schedule is None:
            raise HTTPException(status_code=409, detail="This plan has no schedule.")
        result = apply_plan(tools.calendar, plan_id, draft.result.schedule)
        if not result.ok:
            # Something new clashes since the preview: nothing was written.
            clashes = ", ".join(e.title for e in result.conflicts)
            raise HTTPException(
                status_code=409,
                detail=f"The calendar changed since the preview ({clashes}). "
                "Nothing was written; ask for a new plan.",
            )
        status[plan_id] = "applied"
        return ApplyOut(created=len(result.created), already_there=result.already_there)

    @app.post("/api/plans/{plan_id}/reject")
    def reject(plan_id: str) -> PlanOut:
        _draft(tools, plan_id)
        if status.get(plan_id) == "applied":
            raise HTTPException(status_code=409, detail="This plan is already applied.")
        status[plan_id] = "rejected"
        return get_plan(plan_id)

    if static_dir is not None:
        # The built React app (web/dist), served by this same server in
        # production. Mounted last, so every /api route above wins.
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    return app


def _draft(tools: PlannerTools, plan_id: str) -> Draft:
    draft = tools.drafts.get(plan_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"unknown plan {plan_id!r}")
    return draft


def _event_out(event: Event) -> EventOut:
    return EventOut(
        title=event.title,
        start=event.start,
        end=event.end,
        mine=event.created_by_planner,
    )
