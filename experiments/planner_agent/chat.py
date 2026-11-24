"""Chat with the planner agent in the terminal, showing which tools it calls.

Run:  uv run python -m experiments.planner_agent.chat
Other model (e.g. if the default is overloaded): prefix the command with
      PLANNER_MODEL=gemini-3.5-flash-lite
Empty line to quit.
"""

import asyncio
import logging

from google.adk.runners import InMemoryRunner

from experiments.planner_agent.agent import root_agent
from planner.agent.agent import AgentUnavailableError, run_turn


async def main() -> None:
    # ADK logs every model error with a full traceback before run_turn turns it
    # into one clear message; in this demo, show only that message.
    logging.getLogger("google_adk").setLevel(logging.CRITICAL)
    runner = InMemoryRunner(agent=root_agent, app_name="planner")
    session = await runner.session_service.create_session(
        app_name="planner", user_id="me"
    )
    print(f"Calendar planner demo, model {root_agent.model}, fake calendar.")
    print("Empty line to quit.\n")
    while text := input("you> ").strip():
        try:
            turn = await run_turn(runner, "me", session.id, text)
        except AgentUnavailableError as error:
            print(f"   ! {error}\n")
            continue
        for name in turn.tool_calls:
            print(f"   [tool] {name}")
        print(f"planner> {turn.reply}\n")


if __name__ == "__main__":
    asyncio.run(main())
