"""Tests for scoring a parsed PlanRequest against the gold one."""

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from planner.evals.score import Mistake, match_tasks, score_parse
from planner.parser.schemas import PlanRequest, Task, Window

Z = ZoneInfo("Europe/Zurich")


def z(day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=Z)


ANALYSIS = Task(name="Analysis sheet", duration_min=240, deadline=z(26, 23, 59))
ALGEBRA = Task(name="Linear Algebra", duration_min=180, deadline=z(27, 12))


def request(*tasks: Task, **extra: Any) -> PlanRequest:
    fields = {"horizon_start": z(24, 10), "horizon_end": z(30), "tasks": list(tasks)}
    return PlanRequest.model_validate({**fields, **extra})


GOLD = request(ANALYSIS, ALGEBRA, day_start=time(9))


def test_identical_request_is_exact() -> None:
    assert score_parse(GOLD, GOLD).exact


def test_invalid_output() -> None:
    assert score_parse(GOLD, None).mistakes == [Mistake.INVALID_OUTPUT]


def test_names_are_not_scored_and_order_does_not_matter() -> None:
    renamed = request(
        ALGEBRA.model_copy(update={"name": "LinAlg"}),
        ANALYSIS.model_copy(update={"name": "Analysis"}),
        day_start=time(9),
    )
    assert score_parse(GOLD, renamed).exact


def test_wrong_deadline_is_found_on_the_right_task() -> None:
    wrong = request(
        ANALYSIS.model_copy(update={"deadline": z(26, 12)}), ALGEBRA, day_start=time(9)
    )
    [finding] = score_parse(GOLD, wrong).findings
    assert finding.mistake == Mistake.WRONG_DEADLINE
    assert "'Analysis sheet'" in finding.detail


def test_missing_and_invented_tasks() -> None:
    invented = Task(name="Gym", duration_min=60, deadline=z(25, 20))
    result = score_parse(GOLD, request(ANALYSIS, invented, day_start=time(9)))
    assert sorted(result.mistakes) == [Mistake.EXTRA_TASK, Mistake.MISSING_TASK]


def test_pairing_prefers_the_same_deadline_over_the_same_name() -> None:
    # Predicted "Analysis" has Algebra's deadline and duration: it is Algebra.
    confused = ALGEBRA.model_copy(update={"name": "Analysis"})
    pairs = match_tasks([ANALYSIS, ALGEBRA], [confused])
    assert (ALGEBRA, confused) in pairs
    assert (ANALYSIS, None) in pairs


def test_request_wide_wishes() -> None:
    wrong = request(
        ANALYSIS,
        ALGEBRA,
        day_start=time(10),
        blocked=[Window(start=z(25, 18), end=z(26))],
        max_work_min_per_day=240,
        lunch_start=None,
        lunch_end=None,
        horizon_end=z(29),
    )
    assert set(score_parse(GOLD, wrong).mistakes) == {
        Mistake.WRONG_DAY_HOURS,
        Mistake.WRONG_BLOCKED,
        Mistake.WRONG_DAILY_CAP,
        Mistake.WRONG_LUNCH,
        Mistake.WRONG_HORIZON,
    }


def test_same_blocked_window_written_with_another_offset_is_equal() -> None:
    # UtcDatetime stores UTC, so 18:00+01:00 and 17:00Z are the same moment.
    gold = request(ANALYSIS, blocked=[Window(start=z(25, 18), end=z(26))])
    same = request(
        ANALYSIS,
        blocked=[
            Window.model_validate(
                {"start": "2026-11-25T17:00:00Z", "end": "2026-11-25T23:00:00Z"}
            )
        ],
    )
    assert score_parse(gold, same).exact
