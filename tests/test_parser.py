"""Tests for the request parser. A DummyLM stands in for Gemini: no API calls."""

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from dspy.utils import DummyLM

from planner.parser.parse import (
    PROMPT_VERSION,
    Parser,
    describe_now,
    load_instructions,
)
from planner.parser.schemas import GRANULARITY_MIN, PlanRequest, Task

ZURICH = ZoneInfo("Europe/Zurich")
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=ZURICH)
TEXT = "Analysis sheet due Thursday 23:59, about 4h."


def reply(**task_fields: Any) -> dict[str, Any]:
    """A fake LM answer: one task, with any field overridden."""
    task = {
        "name": "Analysis sheet",
        "duration_min": 240,
        "deadline": "2026-11-26T23:59:00+01:00",
        **task_fields,
    }
    return {
        "plan_request": {
            "horizon_start": "2026-11-24T10:00:00+01:00",
            "horizon_end": "2026-11-30T00:00:00+01:00",
            "tasks": [task],
        }
    }


def parse_with(*answers: dict[str, Any]) -> tuple[Any, DummyLM]:
    lm = DummyLM(list(answers))
    return Parser(lm).parse(TEXT, NOW), lm


def test_valid_answer_becomes_plan_request() -> None:
    result, _ = parse_with(reply())
    assert isinstance(result.request, PlanRequest)
    assert result.errors == []
    task = result.request.tasks[0]
    assert task.duration_min == 240
    assert task.deadline == datetime(2026, 11, 26, 22, 59, tzinfo=UTC)


def test_result_records_prompt_version_and_model() -> None:
    result, _ = parse_with(reply())
    assert result.prompt_version == PROMPT_VERSION
    assert result.model == "dummy"


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("duration_min", 50, "tasks.0.duration_min: Value error, must be a multiple"),
        ("duration_min", "about 4 hours", "tasks.0.duration_min: Input should be"),
        ("deadline", "2026-11-26T23:59:00", "tasks.0.deadline: Input should have"),
        # Real Gemini wrote empty tags for unmentioned fields (prompt v1 draft).
        ("min_block_min", "", "tasks.0.min_block_min: Input should be"),
    ],
)
def test_invalid_answer_keeps_pydantic_reason(
    field: str, value: object, expected: str
) -> None:
    result, _ = parse_with(reply(**{field: value}))
    assert result.request is None
    assert any(reason.startswith(expected) for reason in result.errors)


def test_invalid_answer_costs_exactly_one_call() -> None:
    # DSPy would otherwise retry silently in JSON format (a second LM call).
    _, lm = parse_with(reply(duration_min=50), reply())
    assert len(lm.history) == 1


def test_answer_in_wrong_format_is_an_error_not_a_crash() -> None:
    lm = DummyLM([{"something_else": "hello"}])
    result = Parser(lm).parse(TEXT, NOW)
    assert result.request is None
    assert result.errors


def test_prompt_contains_instructions_text_and_local_now() -> None:
    _, lm = parse_with(reply())
    sent = str(lm.history[-1]["messages"])
    assert "multiples of 15" in sent  # from the instruction file
    assert TEXT in sent
    assert "Tuesday 2026-11-24 10:00 +0100 (Europe/Zurich)" in sent


def test_instructions_match_the_schema() -> None:
    # The prompt states rules in words; the schema enforces them in code.
    instructions = load_instructions(PROMPT_VERSION)
    assert f"multiples of {GRANULARITY_MIN}" in instructions
    default_min_block = Task.model_fields["min_block_min"].default
    assert f"min_block_min is {default_min_block}" in instructions


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 11, 24, 9, 0, tzinfo=UTC), "Tuesday 2026-11-24 10:00 +0100"),
        (datetime(2026, 7, 6, 8, 0, tzinfo=UTC), "Monday 2026-07-06 10:00 +0200"),
    ],
)
def test_describe_now_uses_local_time_and_offset(now: datetime, expected: str) -> None:
    assert describe_now(now, "Europe/Zurich").startswith(expected)


def test_describe_now_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone"):
        describe_now(datetime(2026, 11, 24, 10, 0), "Europe/Zurich")
