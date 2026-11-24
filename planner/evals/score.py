"""Score a parsed PlanRequest against the gold one: every mistake, by category.

Tasks are paired by similarity (deadline, duration, shared name words), since
the parser may name them differently; names themselves are never scored.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from itertools import product
from typing import Protocol

from planner.parser.schemas import PlanRequest, Task


class TaskLike(Protocol):
    """Anything with the three fields used to pair tasks: our strict Task, or
    Baseline A's lenient task list. Read-only, so both fit."""

    @property
    def name(self) -> str: ...
    @property
    def duration_min(self) -> int | None: ...
    @property
    def deadline(self) -> datetime | None: ...


class Mistake(StrEnum):
    INVALID_OUTPUT = "invalid_output"
    MISSING_TASK = "missing_task"
    EXTRA_TASK = "extra_task"
    WRONG_DURATION = "wrong_duration"
    WRONG_DEADLINE = "wrong_deadline"
    WRONG_EARLIEST_START = "wrong_earliest_start"
    WRONG_BLOCK_LENGTH = "wrong_block_length"
    WRONG_DAY_HOURS = "wrong_day_hours"
    WRONG_BLOCKED = "wrong_blocked"
    WRONG_DAILY_CAP = "wrong_daily_cap"
    WRONG_LUNCH = "wrong_lunch"
    WRONG_HORIZON = "wrong_horizon"


@dataclass(frozen=True)
class Finding:
    mistake: Mistake
    detail: str


@dataclass(frozen=True)
class ParseScore:
    findings: list[Finding] = field(default_factory=list)

    @property
    def exact(self) -> bool:
        """True if the parsed request matches the gold one in every scored field."""
        return not self.findings

    @property
    def mistakes(self) -> list[Mistake]:
        return [f.mistake for f in self.findings]


def score_parse(gold: PlanRequest, predicted: PlanRequest | None) -> ParseScore:
    if predicted is None:
        return ParseScore([Finding(Mistake.INVALID_OUTPUT, "no valid PlanRequest")])
    findings = _request_findings(gold, predicted)
    for gold_task, task in match_tasks(gold.tasks, predicted.tasks):
        if gold_task is not None and task is not None:
            findings += _task_findings(gold_task, task)
        elif gold_task is not None:
            findings.append(Finding(Mistake.MISSING_TASK, repr(gold_task.name)))
        elif task is not None:
            findings.append(Finding(Mistake.EXTRA_TASK, repr(task.name)))
    return ParseScore(findings)


def match_tasks[G: TaskLike, P: TaskLike](
    gold: Sequence[G], predicted: Sequence[P]
) -> list[tuple[G | None, P | None]]:
    """Pair each gold task with its most similar predicted task (greedy).

    Pairs with nothing in common are not made: those tasks count as missing
    (gold) and extra (predicted).
    """
    candidates = sorted(
        (
            (_similarity(g, p), gi, pi)
            for (gi, g), (pi, p) in product(enumerate(gold), enumerate(predicted))
        ),
        reverse=True,
    )
    pairs: list[tuple[G | None, P | None]] = []
    used_gold: set[int] = set()
    used_pred: set[int] = set()
    for similarity, gi, pi in candidates:
        if similarity > 0 and gi not in used_gold and pi not in used_pred:
            pairs.append((gold[gi], predicted[pi]))
            used_gold.add(gi)
            used_pred.add(pi)
    pairs += [(g, None) for gi, g in enumerate(gold) if gi not in used_gold]
    pairs += [(None, p) for pi, p in enumerate(predicted) if pi not in used_pred]
    return pairs


def _similarity(gold: TaskLike, predicted: TaskLike) -> float:
    words_gold = set(gold.name.lower().split())
    words_pred = set(predicted.name.lower().split())
    shared = len(words_gold & words_pred) / len(words_gold | words_pred)
    return (
        2 * (gold.deadline == predicted.deadline)
        + 1 * (gold.duration_min == predicted.duration_min)
        + shared
    )


def _task_findings(gold: Task, task: Task) -> list[Finding]:
    name = repr(gold.name)
    checks = [
        (Mistake.WRONG_DURATION, gold.duration_min, task.duration_min),
        (Mistake.WRONG_DEADLINE, gold.deadline, task.deadline),
        (Mistake.WRONG_EARLIEST_START, gold.earliest_start, task.earliest_start),
        (
            Mistake.WRONG_BLOCK_LENGTH,
            (gold.min_block_min, gold.max_block_min),
            (task.min_block_min, task.max_block_min),
        ),
    ]
    return [
        Finding(mistake, f"{name}: expected {want}, got {got}")
        for mistake, want, got in checks
        if want != got
    ]


def _request_findings(gold: PlanRequest, req: PlanRequest) -> list[Finding]:
    def windows(r: PlanRequest) -> set[tuple[str, str]]:
        return {(w.start.isoformat(), w.end.isoformat()) for w in r.blocked}

    checks = [
        (Mistake.WRONG_HORIZON, gold.horizon_end, req.horizon_end),
        (
            Mistake.WRONG_DAY_HOURS,
            (gold.day_start, gold.day_end),
            (req.day_start, req.day_end),
        ),
        (Mistake.WRONG_BLOCKED, windows(gold), windows(req)),
        (Mistake.WRONG_DAILY_CAP, gold.max_work_min_per_day, req.max_work_min_per_day),
        (
            Mistake.WRONG_LUNCH,
            (gold.lunch_start, gold.lunch_end),
            (req.lunch_start, req.lunch_end),
        ),
    ]
    return [
        Finding(mistake, f"expected {want}, got {got}")
        for mistake, want, got in checks
        if want != got
    ]
