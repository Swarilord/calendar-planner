"""The two systems compared in Phase 5, run on one eval case each.

Baseline A ("direct"): Gemini reads the request and writes the schedule itself.
Baseline B ("parser_solver"): Gemini only parses; CP-SAT writes the schedule.
Both are judged the same way: their schedule is checked against the GOLD
request (what the user really asked for), and their feasibility claim against
the case's label.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, TypedDict
from zoneinfo import ZoneInfo

import dspy
from dspy.utils.exceptions import AdapterParseError, LMError
from pydantic import BaseModel, ConfigDict

from planner.agent.tools import TIMEZONE, summarize_events
from planner.calendar.models import Event
from planner.checker.check import Violation, check
from planner.evals.dataset import EvalCase
from planner.evals.score import ParseScore, TaskLike, match_tasks, score_parse
from planner.parser.parse import PROMPT_VERSION as PARSER_PROMPT_VERSION
from planner.parser.parse import (
    Parser,
    ParserUnavailableError,
    describe_now,
    error_reasons,
)
from planner.parser.schemas import Task
from planner.schedule import Schedule, ScheduledBlock
from planner.solver.model import SolveStatus, solve

DIRECT_PROMPT_VERSION = "v1"
PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class Outcome:
    """One baseline's result on one case."""

    case_id: str
    baseline: str
    model: str
    prompt_version: str
    seconds: float
    claimed_feasible: bool | None = None  # None: no usable answer
    schedule: Schedule | None = None
    violations: list[Violation] = field(default_factory=list)  # vs the gold request
    parse: ParseScore | None = None  # Baseline B only
    error: str | None = None  # "invalid: ..." or "unavailable: ..."


class _Meta(TypedDict):
    """The fields every Outcome of one run shares (typed, so mypy checks **meta)."""

    case_id: str
    baseline: str
    model: str
    prompt_version: str


class Baseline(Protocol):
    name: str

    def run(self, case: EvalCase, events: Sequence[Event]) -> Outcome: ...


class ParserSolverBaseline:
    """Baseline B: the DSPy parser, then CP-SAT."""

    name = "parser_solver"

    def __init__(self, lm: Any, prompt_version: str = PARSER_PROMPT_VERSION) -> None:
        self.parser = Parser(lm, prompt_version)

    def run(self, case: EvalCase, events: Sequence[Event]) -> Outcome:
        start = time.monotonic()
        meta: _Meta = {
            "case_id": case.id,
            "baseline": self.name,
            "model": str(self.parser.lm.model),
            "prompt_version": f"parser_{self.parser.prompt_version}",
        }
        try:
            parsed = self.parser.parse(case.text, case.now, _summary(case, events))
        except ParserUnavailableError as error:
            return Outcome(**meta, seconds=_since(start), error=f"unavailable: {error}")
        score = score_parse(case.expected, parsed.request)
        if parsed.request is None:
            return Outcome(
                **meta,
                seconds=_since(start),
                parse=score,
                error=f"invalid: {'; '.join(parsed.errors)}",
            )
        result = solve(parsed.request, events)
        if result.status == SolveStatus.INFEASIBLE or result.schedule is None:
            return Outcome(
                **meta, seconds=_since(start), claimed_feasible=False, parse=score
            )
        schedule = rename_blocks(
            result.schedule, case.expected.tasks, parsed.request.tasks
        )
        return Outcome(
            **meta,
            seconds=_since(start),
            claimed_feasible=True,
            schedule=schedule,
            violations=check(case.expected, events, schedule),
            parse=score,
        )


class StatedTask(BaseModel):
    """A task as Baseline A states it, used ONLY to pair its blocks with gold tasks.

    Deliberately lenient (no 15-minute rule, unknown fields ignored, any field
    may be missing): A is judged on its schedule and its feasibility answer,
    not on how neatly it fills in this side list.
    """

    model_config = ConfigDict(extra="ignore")

    name: str
    duration_min: int | None = None
    deadline: datetime | None = None


class ScheduleDirectly(dspy.Signature):
    """Placeholder; the real instructions come from the prompt file."""

    text: str = dspy.InputField(desc="the user's request, in their own words")
    now: str = dspy.InputField(desc="current local date and time")
    calendar: str = dspy.InputField(desc="existing events, in local time")
    tasks: list[StatedTask] = dspy.OutputField(desc="the tasks you understood")
    feasible: bool = dspy.OutputField(desc="false if the request cannot be met")
    schedule: Schedule = dspy.OutputField(desc="your time blocks")


class DirectBaseline:
    """Baseline A: Gemini plans the schedule itself."""

    name = "direct"

    def __init__(self, lm: Any, prompt_version: str = DIRECT_PROMPT_VERSION) -> None:
        self.lm = lm
        self.prompt_version = prompt_version
        instructions = (PROMPTS_DIR / f"direct_{prompt_version}.md").read_text()
        self.predict = dspy.Predict(ScheduleDirectly.with_instructions(instructions))
        self.adapter = dspy.XMLAdapter(use_json_adapter_fallback=False)

    def run(self, case: EvalCase, events: Sequence[Event]) -> Outcome:
        start = time.monotonic()
        meta: _Meta = {
            "case_id": case.id,
            "baseline": self.name,
            "model": str(self.lm.model),
            "prompt_version": f"direct_{self.prompt_version}",
        }
        with dspy.context(lm=self.lm, adapter=self.adapter):
            try:
                answer = self.predict(
                    text=case.text,
                    now=describe_now(case.now, TIMEZONE),
                    calendar=_summary(case, events),
                )
            except AdapterParseError as error:
                reasons = "; ".join(error_reasons(error))
                return Outcome(
                    **meta, seconds=_since(start), error=f"invalid: {reasons}"
                )
            except LMError as error:
                return Outcome(
                    **meta,
                    seconds=_since(start),
                    error=f"unavailable: {type(error).__name__}",
                )
        if not answer.feasible:
            return Outcome(**meta, seconds=_since(start), claimed_feasible=False)
        schedule = rename_blocks(answer.schedule, case.expected.tasks, answer.tasks)
        return Outcome(
            **meta,
            seconds=_since(start),
            claimed_feasible=True,
            schedule=schedule,
            violations=check(case.expected, events, schedule),
        )


def rename_blocks(
    schedule: Schedule, gold: Sequence[Task], predicted: Sequence[TaskLike]
) -> Schedule:
    """Give each block its gold task's name, so the checker can judge it.

    A block whose task has no gold partner keeps its name; the checker then
    reports it as an unknown (invented) task.
    """
    names = {
        pred.name: g.name
        for g, pred in match_tasks(gold, predicted)
        if g is not None and pred is not None
    }
    return Schedule(
        blocks=[
            ScheduledBlock(
                task_name=names.get(b.task_name, b.task_name), start=b.start, end=b.end
            )
            for b in schedule.blocks
        ]
    )


def _summary(case: EvalCase, events: Sequence[Event]) -> str:
    upcoming = [e for e in events if e.end > case.now]
    return summarize_events(upcoming, ZoneInfo(TIMEZONE))


def _since(start: float) -> float:
    return round(time.monotonic() - start, 2)
