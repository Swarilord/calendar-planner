"""Tests for the two baselines and the runner. DummyLM stands in for Gemini."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import dspy
from dspy.utils import DummyLM

from planner.checker.check import ViolationKind
from planner.evals.baselines import (
    DirectBaseline,
    Outcome,
    ParserSolverBaseline,
    rename_blocks,
)
from planner.evals.dataset import EvalCase, load_calendars, load_cases
from planner.evals.run import run_eval, save, succeeded, summarize
from planner.evals.score import Mistake
from planner.parser.schemas import Task
from planner.schedule import Schedule, ScheduledBlock
from tests.silent_server import silent_server

Z = ZoneInfo("Europe/Zurich")
CASES = {c.id: c for c in load_cases()}
CALENDARS = load_calendars()
C01 = CASES["c01"]  # Analysis sheet, 4h, due Thu 26 Nov 23:59 (feasible)
C44 = CASES["c44"]  # 5h project by today 13:00 (infeasible)


def z(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=Z)


def gold_json(case: EvalCase, **task_changes: Any) -> dict[str, Any]:
    """The gold PlanRequest as a parser answer, optionally changed."""
    request = case.expected.model_dump(mode="json")
    request["tasks"][0].update(task_changes)
    return {"plan_request": request}


def run_b(case: EvalCase, answer: dict[str, Any]) -> Any:
    return ParserSolverBaseline(DummyLM([answer])).run(case, CALENDARS[case.calendar])


def direct_answer(
    blocks: list[tuple[str, datetime, datetime]], feasible: bool = True
) -> dict[str, Any]:
    return {
        "tasks": [
            {
                "name": "Analysis",
                "duration_min": 240,
                "deadline": z(26, 23, 59).isoformat(),
            }
        ],
        "feasible": feasible,
        "schedule": {
            "blocks": [
                {"task_name": n, "start": s.isoformat(), "end": e.isoformat()}
                for n, s, e in blocks
            ]
        },
    }


def run_a(case: EvalCase, answer: dict[str, Any]) -> Any:
    return DirectBaseline(DummyLM([answer])).run(case, CALENDARS[case.calendar])


# --- Baseline B: parser + solver ---


def test_b_with_a_perfect_parse_succeeds() -> None:
    outcome = run_b(C01, gold_json(C01))
    assert outcome.parse.exact
    assert outcome.violations == []
    assert succeeded(outcome, C01)
    assert outcome.prompt_version == "parser_v1" and outcome.model == "dummy"


def test_b_parse_mistake_shows_up_against_the_gold_request() -> None:
    # The parser reads 3h instead of 4h: the solver's plan is valid for the
    # parser's request, but 60 minutes short for what the user asked.
    outcome = run_b(C01, gold_json(C01, duration_min=180))
    assert outcome.parse.mistakes == [Mistake.WRONG_DURATION]
    assert [v.kind for v in outcome.violations] == [ViolationKind.WRONG_TOTAL]
    assert not succeeded(outcome, C01)


def test_b_says_infeasible_for_an_impossible_case() -> None:
    outcome = run_b(C44, gold_json(C44))
    assert outcome.claimed_feasible is False
    assert succeeded(outcome, C44)


def test_b_invalid_parse_is_a_failure() -> None:
    outcome = run_b(C01, gold_json(C01, duration_min=50))
    assert outcome.error is not None and outcome.error.startswith("invalid")
    assert outcome.parse.mistakes == [Mistake.INVALID_OUTPUT]
    assert not succeeded(outcome, C01)


def test_b_outage_is_recorded_as_unavailable() -> None:
    with silent_server() as url:
        lm = dspy.LM(
            "gemini/x",
            api_key="fake",
            api_base=url,
            cache=False,
            num_retries=0,
            timeout=1,
        )
        outcome = ParserSolverBaseline(lm).run(C01, CALENDARS[C01.calendar])
    assert outcome.error is not None and outcome.error.startswith("unavailable")


# --- Baseline A: Gemini schedules directly ---


def test_a_valid_schedule_with_its_own_task_name_succeeds() -> None:
    # Tue 15:00-19:00: after Tuesday's lecture, before 20:00; named "Analysis".
    outcome = run_a(C01, direct_answer([("Analysis", z(24, 15), z(24, 19))]))
    assert outcome.violations == []
    assert outcome.schedule.blocks[0].task_name == "Analysis sheet"  # gold name
    assert succeeded(outcome, C01)


def test_a_clash_with_a_lecture_is_caught_by_the_checker() -> None:
    outcome = run_a(C01, direct_answer([("Analysis", z(24, 13), z(24, 17))]))
    assert ViolationKind.CLASHES_WITH_EVENT in [v.kind for v in outcome.violations]
    assert not succeeded(outcome, C01)


def test_a_wrongly_giving_up_is_a_failure() -> None:
    outcome = run_a(C01, direct_answer([], feasible=False))
    assert outcome.claimed_feasible is False
    assert not succeeded(outcome, C01)


def test_rename_keeps_invented_task_names() -> None:
    gold = [Task(name="Analysis sheet", duration_min=240, deadline=z(26, 23, 59))]
    predicted = [Task(name="Gym", duration_min=60, deadline=z(24, 20))]
    schedule = Schedule(
        blocks=[ScheduledBlock(task_name="Gym", start=z(24, 18), end=z(24, 19))]
    )
    assert rename_blocks(schedule, gold, predicted).blocks[0].task_name == "Gym"


# --- runner ---


def test_run_summarize_and_save(tmp_path: Path) -> None:
    cases = [C01, C44]
    baseline = ParserSolverBaseline(DummyLM([gold_json(C01), gold_json(C44)]))
    outcomes = run_eval(baseline, cases, CALENDARS, progress=lambda line: None)
    summary = summarize(outcomes, cases)
    assert summary["success_rate"] == 1.0
    assert summary["feasibility_accuracy"] == 1.0
    assert summary["parse_exact_rate"] == 1.0

    path = save(outcomes, summary, "train", directory=tmp_path)
    record = json.loads(path.read_text())
    assert record["model"] == "dummy" and record["prompt_version"] == "parser_v1"
    assert [o["case_id"] for o in record["outcomes"]] == ["c01", "c44"]


def test_outages_are_left_out_of_the_rates() -> None:
    def outcome(case_id: str, **fields: Any) -> Outcome:
        return Outcome(
            case_id=case_id, baseline="x", model="m", prompt_version="v", **fields
        )

    outcomes = [
        outcome("c01", seconds=1.0, claimed_feasible=True),
        outcome("c44", seconds=1.0, error="unavailable: timeout"),
    ]
    summary = summarize(outcomes, [C01, C44])
    assert summary["unavailable"] == 1
    assert summary["success_rate"] == 1.0  # 1 of 1 answered case
