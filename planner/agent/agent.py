"""The conversation agent: Gemini in ADK, with the planner tools.

The agent only talks and chooses tools; every tool is plain, tested Python in
tools.py. run_turn() sends one user message through the ADK loop and turns a
silent or overloaded Gemini into a clear AgentUnavailableError.
"""

from dataclasses import dataclass, field
from pathlib import Path

import httpx
from google.adk.agents.llm_agent import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import Runner
from google.genai import errors as genai_errors
from google.genai import types

from planner.agent.tools import PlannerTools
from planner.llm import TIMEOUT_S, agent_config, model_name

AGENT_PROMPT_VERSION = "v1"
PROMPTS_DIR = Path(__file__).parent / "prompts"


class AgentUnavailableError(Exception):
    """Gemini did not answer in time or reported an error."""


@dataclass(frozen=True)
class Turn:
    reply: str  # the agent's final answer to the user
    tool_calls: list[str] = field(default_factory=list)  # tool names, in order


def load_instruction(version: str = AGENT_PROMPT_VERSION) -> str:
    return (PROMPTS_DIR / f"agent_{version}.md").read_text(encoding="utf-8")


def build_agent(
    tools: PlannerTools,
    model: str | BaseLlm | None = None,
    timeout_s: float = TIMEOUT_S,
) -> Agent:
    return Agent(
        name="calendar_planner",
        model=model or model_name(),
        description="Plans study time around the user's calendar.",
        instruction=load_instruction(),
        # Bound methods: ADK reads each name, docstring and parameters.
        # There is deliberately no tool that writes to the calendar.
        tools=[
            tools.get_now,
            tools.get_events,
            tools.get_free_slots,
            tools.propose_plan,
            tools.revise_plan,
            tools.explain_infeasible,
        ],
        generate_content_config=agent_config(timeout_s),
    )


async def run_turn(runner: Runner, user_id: str, session_id: str, text: str) -> Turn:
    """Send one user message; return the agent's reply and the tools it used."""
    message = types.Content(role="user", parts=[types.Part(text=text)])
    calls: list[str] = []
    reply: list[str] = []
    try:
        async for event in runner.run_async(
            user_id=user_id, session_id=session_id, new_message=message
        ):
            parts = event.content.parts if event.content else None
            for part in parts or []:
                if part.function_call and part.function_call.name:
                    calls.append(part.function_call.name)
                elif part.text and not part.thought and event.is_final_response():
                    reply.append(part.text)
    except (httpx.HTTPError, genai_errors.APIError) as error:
        raise AgentUnavailableError(
            "Gemini did not answer in time or is overloaded. "
            "Please try again in a minute."
        ) from error
    return Turn("".join(reply).strip(), calls)
