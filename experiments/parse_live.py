"""Manual check: parse one request with the real Gemini (needs GOOGLE_API_KEY).

Not a test: tests use DummyLM and never call Gemini.
Run:  uv run python -m experiments.parse_live "Analysis due Thursday, about 4h"
"""

import sys
from datetime import UTC, datetime

from dotenv import load_dotenv

from planner.llm import parser_lm
from planner.parser.parse import Parser

EXAMPLE = (
    "Analysis sheet due Thursday 23:59, about 4h. Linear Algebra due Friday noon, "
    "about 3h. Nothing before 9, keep Wednesday evening free."
)


def main() -> None:
    load_dotenv()  # reads GOOGLE_API_KEY from .env in the repo root
    text = " ".join(sys.argv[1:]) or EXAMPLE
    lm = parser_lm()  # shared settings: model, timeout, retry, thinking level
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
