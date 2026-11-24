"""Chat with the planner agent in the terminal, showing which tools it calls.

Run:  uv run python -m experiments.planner_agent.chat
Empty line to quit.
"""

import asyncio

from google.adk.runners import InMemoryRunner

from experiments.planner_agent.agent import root_agent
from planner.agent.agent import AgentUnavailableError, run_turn


async def main() -> None:
    runner = InMemoryRunner(agent=root_agent, app_name="planner")
    session = await runner.session_service.create_session(
        app_name="planner", user_id="me"
    )
    print("Calendar planner demo (fake calendar). Empty line to quit.\n")
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
