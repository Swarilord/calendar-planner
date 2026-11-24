"""The eval dataset: user requests with a fixed "now", a fixed calendar and the
gold PlanRequest a careful human would write. Conventions: evals/README.md."""

import json
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

from planner.calendar.models import Event
from planner.common import Schema, UtcDatetime
from planner.parser.schemas import PlanRequest

EVALS_DIR = Path(__file__).resolve().parents[2] / "evals"
CASES_VERSION = "v1"


class EvalCase(Schema):
    id: str
    split: Literal["train", "test"]  # test = held out: never used for tuning
    tags: list[str]
    text: str
    now: UtcDatetime
    calendar: str  # a name in calendars.json
    expect_feasible: bool
    expected: PlanRequest  # the gold answer


def load_cases(version: str = CASES_VERSION) -> list[EvalCase]:
    lines = (EVALS_DIR / f"cases_{version}.jsonl").read_text(encoding="utf-8")
    return [EvalCase.model_validate_json(line) for line in lines.splitlines() if line]


def load_calendars() -> dict[str, list[Event]]:
    raw = json.loads((EVALS_DIR / "calendars.json").read_text(encoding="utf-8"))
    return TypeAdapter(dict[str, list[Event]]).validate_python(raw)
