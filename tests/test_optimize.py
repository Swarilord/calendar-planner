"""Tests for the GEPA pipeline's parts (the GEPA run itself needs real Gemini)."""

from pathlib import Path

import dspy
import pytest
from dspy.utils import DummyLM

from planner.evals.dataset import load_calendars, load_cases
from planner.evals.optimize import (
    ParserProgram,
    metric,
    next_version,
    save_instructions,
    score,
    split_for_gepa,
    to_example,
)
from planner.parser.parse import load_instructions

CASES = load_cases()
C01 = next(c for c in CASES if c.id == "c01")
GOLD = C01.expected


def test_exact_parse_scores_one() -> None:
    assert score(GOLD, GOLD) == (1.0, "Correct.")


def test_invalid_output_scores_zero() -> None:
    assert score(GOLD, None)[0] == 0.0


def test_horizon_mistake_costs_less_than_a_deadline_mistake() -> None:
    wrong_horizon = GOLD.model_copy(update={"horizon_end": GOLD.tasks[0].deadline})
    task = GOLD.tasks[0].model_copy(
        update={"deadline": GOLD.horizon_start.replace(hour=20)}
    )
    wrong_deadline = GOLD.model_copy(update={"tasks": [task]})
    assert score(GOLD, wrong_horizon)[0] == pytest.approx(0.9)
    value, feedback = score(GOLD, wrong_deadline)
    assert value == pytest.approx(0.75)
    assert "wrong_deadline: 'Analysis sheet': expected" in feedback


def test_metric_returns_score_and_feedback_for_gepa() -> None:
    example = to_example(C01, load_calendars()[C01.calendar])
    result = metric(example, dspy.Prediction(plan_request=GOLD))
    assert (result.score, result.feedback) == (1.0, "Correct.")
    assert metric(example, dspy.Prediction()).score == 0.0  # no answer at all


def test_gepa_never_sees_the_test_split() -> None:
    reflect_on, select_with = split_for_gepa(CASES)
    assert (len(reflect_on), len(select_with)) == (20, 15)
    used = {c.id for c in reflect_on + select_with}
    assert not used & {c.id for c in CASES if c.split == "test"}
    assert {c.split for c in reflect_on + select_with} == {"train"}


def test_example_inputs_match_the_parser() -> None:
    example = to_example(C01, load_calendars()[C01.calendar])
    assert set(example.inputs().keys()) == {"text", "now", "calendar_summary"}
    assert example.now.startswith("Tuesday 2026-11-24 10:00 +0100")
    assert "Linear Algebra lecture" in example.calendar_summary


def test_program_starts_from_the_current_prompt_and_parses() -> None:
    program = ParserProgram(load_instructions("v1"))
    assert "multiples of 15" in program.parse.signature.instructions
    lm = DummyLM([{"plan_request": GOLD.model_dump(mode="json")}])
    with dspy.context(lm=lm, adapter=dspy.XMLAdapter(use_json_adapter_fallback=False)):
        prediction = program(**to_example(C01, []).inputs())
    assert prediction.plan_request == GOLD


def test_new_versions_never_overwrite_old_ones(tmp_path: Path) -> None:
    (tmp_path / "parser_v1.md").write_text("old")
    assert next_version(tmp_path) == "v2"
    save_instructions("new instructions", "v2", tmp_path)
    assert next_version(tmp_path) == "v3"
    with pytest.raises(FileExistsError):
        save_instructions("overwrite attempt", "v1", tmp_path)
    assert (tmp_path / "parser_v1.md").read_text() == "old"
