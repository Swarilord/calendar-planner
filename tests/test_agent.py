"""Tests for the ADK agent. A scripted fake model replaces Gemini, so the real
ADK loop (tool calls, tool results, final answer) runs without an API key."""

import asyncio
import socket
import threading
import time
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from planner.agent.agent import (
    AgentUnavailableError,
    Turn,
    build_agent,
    load_instruction,
    run_turn,
)
from planner.agent.tools import PlannerTools
from planner.llm import DEFAULT_MODEL, parser_lm
from tests.test_agent_tools import NOW, z
from tests.test_agent_tools import make_tools as make_planner_tools

TOOL_NAMES = {
    "get_now",
    "get_events",
    "get_free_slots",
    "propose_plan",
    "revise_plan",
    "explain_infeasible",
}


class ScriptedGemini(BaseLlm):
    """Stands in for Gemini: each call returns the next scripted reply."""

    model: str = "scripted"
    script: list[types.Content] = []
    requests: list[LlmRequest] = []

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse]:
        self.requests.append(llm_request)
        yield LlmResponse(content=self.script[len(self.requests) - 1])


def call(name: str, **args: Any) -> types.Content:
    part = types.Part(function_call=types.FunctionCall(name=name, args=args))
    return types.Content(role="model", parts=[part])


def say(text: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=text)])


def chat(tools: PlannerTools, model: BaseLlm, *messages: str) -> list[Turn]:
    async def run() -> list[Turn]:
        runner = InMemoryRunner(agent=build_agent(tools, model), app_name="test")
        session = await runner.session_service.create_session(
            app_name="test", user_id="me"
        )
        return [await run_turn(runner, "me", session.id, m) for m in messages]

    return asyncio.run(run())


# --- how the agent is built ---


def test_agent_has_exactly_the_six_tools() -> None:
    tools, _, _ = make_planner_tools()
    agent = build_agent(tools)
    assert {tool.__name__ for tool in agent.tools} == TOOL_NAMES  # type: ignore[union-attr]


def test_instruction_has_the_brief_rules_and_no_placeholders() -> None:
    instruction = load_instruction()
    assert "Call get_now" in instruction
    assert "Confirm" in instruction
    # ADK reads {name} in an instruction as a session-state variable.
    assert "{" not in instruction and "}" not in instruction


def test_agent_calls_have_a_timeout_retry_and_low_thinking() -> None:
    tools, _, _ = make_planner_tools()
    config = build_agent(tools).generate_content_config
    assert config is not None and config.http_options is not None
    assert config.http_options.timeout == 30_000  # milliseconds in google-genai
    assert config.http_options.retry_options is not None
    assert config.http_options.retry_options.attempts == 2
    assert config.thinking_config is not None
    assert config.thinking_config.thinking_level == types.ThinkingLevel.LOW


def test_parser_lm_has_the_same_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "not-a-real-key")
    lm = parser_lm()
    assert lm.kwargs["timeout"] == 30  # seconds in DSPy
    assert lm.kwargs["reasoning_effort"] == "low"
    assert lm.num_retries == 1


def test_model_can_be_switched_without_code_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools, _, _ = make_planner_tools()
    monkeypatch.delenv("PLANNER_MODEL", raising=False)
    assert build_agent(tools).model == DEFAULT_MODEL
    monkeypatch.setenv("PLANNER_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setenv("GOOGLE_API_KEY", "not-a-real-key")
    assert build_agent(tools).model == "gemini-3.5-flash-lite"
    assert parser_lm().model == "gemini/gemini-3.5-flash-lite"


# --- the full ADK loop with a scripted model ---


def test_plan_request_runs_the_tool_and_returns_the_answer() -> None:
    tools, _, calendar = make_planner_tools()
    before = calendar.list_events(z(1, 0), z(30, 0))
    model = ScriptedGemini(
        script=[
            call("get_now"),
            call("propose_plan", request_text="Analysis, 2h, due today 18:00"),
            say("Here is a draft. Click Confirm to add it."),
        ]
    )
    [turn] = chat(tools, model, "Plan 2h for Analysis today")

    assert turn.tool_calls == ["get_now", "propose_plan"]
    assert turn.reply == "Here is a draft. Click Confirm to add it."
    assert "plan-1" in tools.drafts
    assert calendar.list_events(z(1, 0), z(30, 0)) == before  # nothing written

    # The tool's result really went back to the model before its last answer.
    last_request = model.requests[-1]
    responses = [
        p.function_response
        for c in last_request.contents
        for p in c.parts or []
        if p.function_response
    ]
    assert responses[-1] is not None and responses[-1].name == "propose_plan"
    assert (responses[-1].response or {})["status"] == "ok"


def test_model_sees_instruction_and_all_tools() -> None:
    tools, _, _ = make_planner_tools()
    model = ScriptedGemini(script=[say("Hi!")])
    chat(tools, model, "hello")
    config = model.requests[0].config
    assert config is not None
    assert "Call get_now" in str(config.system_instruction)
    declared = {
        d.name
        for tool in config.tools or []
        for d in getattr(tool, "function_declarations", None) or []
    }
    assert declared == TOOL_NAMES


def test_get_now_tool_answers_with_the_injected_clock() -> None:
    tools, _, _ = make_planner_tools()
    model = ScriptedGemini(script=[call("get_now"), say("It is Tuesday.")])
    chat(tools, model, "What day is it?")
    response = [
        p.function_response
        for c in model.requests[-1].contents
        for p in c.parts or []
        if p.function_response
    ][-1]
    assert response is not None and response.response is not None
    assert response.response["weekday"] == "Tuesday"
    assert response.response["now"] == NOW.isoformat(timespec="minutes")


# --- Gemini down: a clear error instead of a frozen program ---


def test_silent_gemini_becomes_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "not-a-real-key")
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    held: list[object] = []

    def accept_and_never_reply() -> None:
        try:
            while True:
                held.append(server.accept())
        except OSError:
            pass  # the test closed the server

    threading.Thread(target=accept_and_never_reply, daemon=True).start()
    silent = Gemini(
        model="gemini-3.6-flash", base_url=f"http://127.0.0.1:{server.getsockname()[1]}"
    )
    tools, _, _ = make_planner_tools()

    async def run() -> None:
        agent = build_agent(tools, silent, timeout_s=0.5)
        runner = InMemoryRunner(agent=agent, app_name="test")
        session = await runner.session_service.create_session(
            app_name="test", user_id="me"
        )
        await run_turn(runner, "me", session.id, "hello")

    start = time.monotonic()
    with pytest.raises(AgentUnavailableError, match="try again"):
        asyncio.run(run())
    assert time.monotonic() - start < 10  # two short attempts, not a hang
    server.close()
