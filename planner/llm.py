"""Settings for every Gemini call (parser and agent), kept in one place.

Each call has a time limit and at most one retry, so an overloaded or silent
Gemini becomes a clear error instead of a program that looks frozen.
"""

import os
from typing import Any

import dspy
from google.genai import types

MODEL = "gemini-3.6-flash"
TIMEOUT_S = 30  # per attempt
ATTEMPTS = 2  # the first try plus one retry
# Gemini 3 thinks before answering; "low" was measured at ~13 s per parse vs
# ~56 s at the default level (Phase 4.1).
THINKING = "low"


def parser_lm(model: str = MODEL) -> Any:
    """The DSPy LM for the request parser. DSPy's timeout is in seconds."""
    return dspy.LM(
        f"gemini/{model}",
        api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0.0,
        cache=False,  # always ask Gemini; evals must not reuse old answers
        num_retries=ATTEMPTS - 1,
        timeout=TIMEOUT_S,
        reasoning_effort=THINKING,
    )


def agent_config(timeout_s: float = TIMEOUT_S) -> types.GenerateContentConfig:
    """Call settings for the ADK agent. google-genai's timeout is in milliseconds."""
    return types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        http_options=types.HttpOptions(
            timeout=int(timeout_s * 1000),
            retry_options=types.HttpRetryOptions(attempts=ATTEMPTS),
        ),
    )
