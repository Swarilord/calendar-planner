"""Automatic checks on the eval dataset's gold answers."""

from collections import Counter

import pytest

from planner.checker.check import check
from planner.evals.dataset import EvalCase, load_calendars, load_cases
from planner.solver.model import SolveStatus, solve

CASES = load_cases()
CALENDARS = load_calendars()


def test_ids_are_unique_and_split_is_35_15() -> None:
    assert len({c.id for c in CASES}) == len(CASES) == 50
    assert Counter(c.split for c in CASES) == {"train": 35, "test": 15}


def test_every_case_names_an_existing_calendar() -> None:
    assert {c.calendar for c in CASES} <= set(CALENDARS)


def test_test_split_covers_the_hard_kinds() -> None:
    test_tags = {tag for c in CASES if c.split == "test" for tag in c.tags}
    assert {"infeasible", "dst", "recurring", "multi_task", "next_week"} <= test_tags


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_gold_follows_the_conventions(case: EvalCase) -> None:
    gold = case.expected
    assert gold.horizon_start == case.now  # the horizon starts now
    assert gold.horizon_end >= max(t.deadline for t in gold.tasks)  # covers deadlines
    assert all(t.deadline > case.now for t in gold.tasks)


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_solver_agrees_with_the_feasibility_label(case: EvalCase) -> None:
    events = CALENDARS[case.calendar]
    result = solve(case.expected, events)
    if case.expect_feasible:
        assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)
        assert result.schedule is not None
        assert check(case.expected, events, result.schedule) == []
    else:
        assert result.status == SolveStatus.INFEASIBLE
