"""Manual check: parse one request with the real Gemini (needs GOOGLE_API_KEY).

Not a test: tests use DummyLM and never call Gemini.
Run:  uv run python -m experiments.parse_live "Analysis due Thursday, about 4h"
"""

import os
import sys
from datetime import UTC, datetime

import dspy
from dotenv import load_dotenv

from planner.parser.parse import Parser

MODEL = "gemini-3.6-flash"
EXAMPLE = (
    "Analysis sheet due Thursday 23:59, about 4h. Linear Algebra due Friday noon, "
    "about 3h. Nothing before 9, keep Wednesday evening free."
)


def main() -> None:
    load_dotenv()  # reads GOOGLE_API_KEY from .env in the repo root
    text = " ".join(sys.argv[1:]) or EXAMPLE
    lm = dspy.LM(
        f"gemini/{MODEL}",
        api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0.0,  # same text -> (nearly) the same answer
        cache=False,  # always ask Gemini, never an old cached answer
        num_retries=1,  # fail fast instead of retrying silently (Phase 1 lesson)
        timeout=30,  # seconds; without it the engine's default can wait very long
        # Gemini 3 thinks before answering: "high" took 56 s, "low" about 13 s.
        reasoning_effort="low",
    )
    result = Parser(lm).parse(text, datetime.now(UTC))
    print(f"model={result.model}  prompt={result.prompt_version}\n")
    if result.request is None:
        print("INVALID:")
        for reason in result.errors:
            print("  -", reason)
    else:
        print(result.request.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
