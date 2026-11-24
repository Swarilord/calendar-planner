"""Settings for every Gemini call (parser and agent), kept in one place.

Each call has a time limit and at most one retry, so an overloaded or silent
Gemini becomes a clear error instead of a program that looks frozen.
"""

import os
from typing import Any

import dspy
from google.genai import types

DEFAULT_MODEL = "gemini-3.6-flash"
TIMEOUT_S = 30  # per attempt
ATTEMPTS = 2  # the first try plus one retry
# Gemini 3 thinks before answering; "low" was measured at ~13 s per parse vs
# ~56 s at the default level (Phase 4.1).
THINKING = "low"


def model_name() -> str:
    """The Gemini model to use: PLANNER_MODEL if set (e.g. when the default is
    overloaded), else DEFAULT_MODEL. Read at call time, so tests can set it."""
    return os.environ.get("PLANNER_MODEL", DEFAULT_MODEL)


def parser_lm(model: str | None = None, retries: int = ATTEMPTS - 1) -> Any:
    """The DSPy LM for the request parser. DSPy's timeout is in seconds.

    DSPy waits before each retry, so long offline runs (GEPA) pass more retries
    to ride out per-minute rate limits instead of failing cases.
    """
    return dspy.LM(
        f"gemini/{model or model_name()}",
        api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0.0,
        cache=False,  # always ask Gemini; evals must not reuse old answers
        num_retries=retries,
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


def reflection_lm(model: str | None = None, retries: int = 8) -> Any:
    """The LM GEPA uses to rewrite instructions: more creative, longer answers."""
    return dspy.LM(
        f"gemini/{model or model_name()}",
        api_key=os.environ["GOOGLE_API_KEY"],
        temperature=1.0,  # GEPA's docs recommend a creative reflection model
        max_tokens=16000,
        cache=False,
        num_retries=retries,
        timeout=2 * TIMEOUT_S,  # it writes a whole new instruction
    )
