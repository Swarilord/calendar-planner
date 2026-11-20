"""Run the hello agent on a few questions and print each step of the agent loop.

Shows when Gemini asks for a tool, what our code returns, and the final answer.
Calls the real Gemini API (needs GOOGLE_API_KEY in .env).

Run from the repo root:  uv run python -m experiments.hello_agent.trace
"""

import asyncio

from dotenv import load_dotenv
from google.adk.runners import InMemoryRunner
from google.genai import types

from experiments.hello_agent.agent import root_agent

QUESTIONS = [
    "What day is it today?",
    "How many hours until midnight?",
    "What's the capital of Switzerland?",
]


async def main() -> None:
    load_dotenv()  # searches upward from this file's folder for .env
    runner = InMemoryRunner(agent=root_agent, app_name="trace")
    for question in QUESTIONS:
        # A new session per question, so earlier answers don't influence later ones.
        session = await runner.session_service.create_session(
            app_name="trace", user_id="me"
        )
        print(f"\n=== YOU: {question}")
        message = types.Content(role="user", parts=[types.Part(text=question)])
        async for event in runner.run_async(
            user_id="me", session_id=session.id, new_message=message
        ):
            if event.content is None or not event.content.parts:
                continue
            for part in event.content.parts:
                if part.function_call:
                    args = dict(part.function_call.args or {})
                    print(f"  [Gemini asks to call] {part.function_call.name}({args})")
                elif part.function_response:
                    print(f"  [our code returned]   {part.function_response.response}")
                elif part.text and not part.thought:
                    print(f"  [Gemini answers]      {part.text.strip()}")


if __name__ == "__main__":
    asyncio.run(main())
