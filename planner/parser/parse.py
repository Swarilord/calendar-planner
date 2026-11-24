"""Request parser: the user's text -> a validated PlanRequest, via DSPy.

DSPy builds the prompt from the ParseRequest signature plus the instruction file
for PROMPT_VERSION, calls the LM once, and validates the answer into a
PlanRequest. We switch off DSPy's automatic second attempt and catch the
validation error ourselves, so every failure keeps Pydantic's exact reason and
each parse() is exactly one LM call (what the evals need to measure).
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dspy
from dspy.utils.exceptions import AdapterParseError, LMError
from pydantic import ValidationError

from planner.parser.schemas import PlanRequest

PROMPT_VERSION = "v1"
PROMPTS_DIR = Path(__file__).parent / "prompts"


class ParserUnavailableError(Exception):
    """The LM did not answer (timeout, overload, quota, ...): not the user's fault."""


class ParseRequest(dspy.Signature):
    """Placeholder; the real instructions come from the prompt file."""

    text: str = dspy.InputField(desc="the user's request, in their own words")
    now: str = dspy.InputField(desc="current local date and time")
    calendar_summary: str = dspy.InputField(desc="existing events, for context")
    plan_request: PlanRequest = dspy.OutputField()


@dataclass(frozen=True)
class ParseResult:
    request: PlanRequest | None  # None if the LM's answer was invalid
    errors: list[str] = field(default_factory=list)  # why it was invalid
    prompt_version: str = PROMPT_VERSION
    model: str = ""


def load_instructions(version: str) -> str:
    return (PROMPTS_DIR / f"parser_{version}.md").read_text(encoding="utf-8")


class Parser:
    def __init__(self, lm: dspy.BaseLM, prompt_version: str = PROMPT_VERSION):
        self.lm = lm
        self.prompt_version = prompt_version
        signature = ParseRequest.with_instructions(load_instructions(prompt_version))
        self.predict = dspy.Predict(signature)
        # No hidden retry in another format: one parse() = one LM call.
        self.adapter = dspy.XMLAdapter(use_json_adapter_fallback=False)

    def parse(
        self,
        text: str,
        now: datetime,
        calendar_summary: str = "",
        timezone: str = "Europe/Zurich",
    ) -> ParseResult:
        with dspy.context(lm=self.lm, adapter=self.adapter):
            try:
                prediction = self.predict(
                    text=text,
                    now=describe_now(now, timezone),
                    calendar_summary=calendar_summary or "(no events)",
                )
            except AdapterParseError as error:  # an answer, but an invalid one
                return self._result(None, error_reasons(error))
            except LMError as error:  # no usable answer at all
                raise ParserUnavailableError(
                    f"{self.lm.model} did not answer: {type(error).__name__}"
                ) from error
        return self._result(prediction.plan_request, [])

    def _result(self, request: PlanRequest | None, errors: list[str]) -> ParseResult:
        return ParseResult(request, errors, self.prompt_version, str(self.lm.model))


def describe_now(now: datetime, timezone: str) -> str:
    """E.g. 'Tuesday 2026-11-24 10:00 +0100 (Europe/Zurich)'."""
    if now.tzinfo is None:
        raise ValueError("now must carry a timezone")
    local = now.astimezone(ZoneInfo(timezone))
    return f"{local:%A %Y-%m-%d %H:%M %z} ({timezone})"


def error_reasons(error: AdapterParseError) -> list[str]:
    """Pydantic's exact reasons if the answer had the wrong content, else the
    adapter's message (answer not in the expected format at all)."""
    cause = error.__cause__
    if isinstance(cause, ValidationError):
        return [
            f"{'.'.join(str(part) for part in e['loc'])}: {e['msg']}"
            for e in cause.errors()
        ]
    return [error.message or "answer was not in the expected format"]
