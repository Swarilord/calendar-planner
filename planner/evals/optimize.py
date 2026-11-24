"""Phase 6: improve the parser's instructions with GEPA, on the train split only.

GEPA runs the parser on training cases, shows a reflection LM what went wrong
(our scorer's findings as text), lets it rewrite the instructions, and keeps
the version that scores best on a validation part of the train split. The
held-out test split is never used here.

Run:  uv run python -m planner.evals.optimize --budget 150
Writes the result as a NEW prompt version (parser_v2.md, ...); v1 stays frozen.
"""

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import dspy
from dotenv import load_dotenv

from planner.agent.tools import TIMEZONE, summarize_events
from planner.calendar.models import Event
from planner.evals.dataset import EvalCase, load_calendars, load_cases
from planner.evals.score import Mistake, score_parse
from planner.llm import model_name, parser_lm, reflection_lm
from planner.parser.parse import (
    PROMPT_VERSION,
    PROMPTS_DIR,
    ParseRequest,
    describe_now,
    load_instructions,
)
from planner.parser.schemas import PlanRequest

REFLECTION_CASES = 20  # the rest of the train split is GEPA's validation set
MISTAKE_PENALTY = 0.25  # per mistake that can change the plan
HORIZON_PENALTY = 0.1  # wrong_horizon rarely changes the plan (Phase 5 runs)


class ParserProgram(dspy.Module):  # type: ignore[misc]
    """The parser's DSPy part as a module, so GEPA can rewrite its instructions."""

    def __init__(self, instructions: str) -> None:
        super().__init__()
        self.parse = dspy.Predict(ParseRequest.with_instructions(instructions))

    def forward(self, text: str, now: str, calendar_summary: str) -> Any:
        return self.parse(text=text, now=now, calendar_summary=calendar_summary)


def score(gold: PlanRequest, predicted: PlanRequest | None) -> tuple[float, str]:
    """A score in [0, 1] and the feedback text GEPA's reflection LM reads."""
    result = score_parse(gold, predicted)
    if Mistake.INVALID_OUTPUT in result.mistakes:
        return 0.0, "The answer was not a valid PlanRequest."
    if result.exact:
        return 1.0, "Correct."
    penalty = sum(
        HORIZON_PENALTY if m == Mistake.WRONG_HORIZON else MISTAKE_PENALTY
        for m in result.mistakes
    )
    lines = [f"- {f.mistake.value}: {f.detail}" for f in result.findings]
    return max(0.0, 1 - penalty), "Mistakes:\n" + "\n".join(lines)


def metric(
    example: Any,
    prediction: Any,
    trace: Any = None,
    pred_name: str | None = None,
    pred_trace: Any = None,
) -> Any:
    """GEPA's metric: score plus written feedback (see dspy.GEPA's docs)."""
    value, feedback = score(example.gold, getattr(prediction, "plan_request", None))
    return dspy.Prediction(score=value, feedback=feedback)


def to_example(case: EvalCase, events: Sequence[Event]) -> Any:
    upcoming = [e for e in events if e.end > case.now]
    return dspy.Example(
        text=case.text,
        now=describe_now(case.now, TIMEZONE),
        calendar_summary=summarize_events(upcoming, ZoneInfo(TIMEZONE)),
        gold=case.expected,
    ).with_inputs("text", "now", "calendar_summary")


def split_for_gepa(
    cases: Sequence[EvalCase],
) -> tuple[list[EvalCase], list[EvalCase]]:
    """Train cases only: the first 20 (by id) to reflect on, the rest to select."""
    train = sorted((c for c in cases if c.split == "train"), key=lambda c: c.id)
    return train[:REFLECTION_CASES], train[REFLECTION_CASES:]


def next_version(prompts_dir: Path = PROMPTS_DIR) -> str:
    numbers = [
        int(p.stem.removeprefix("parser_v")) for p in prompts_dir.glob("parser_v*.md")
    ]
    return f"v{max(numbers, default=0) + 1}"


def save_instructions(text: str, version: str, prompts_dir: Path = PROMPTS_DIR) -> Path:
    """Write a new prompt version; never overwrite one (they are frozen once used)."""
    path = prompts_dir / f"parser_{version}.md"
    if path.exists():
        raise FileExistsError(
            f"{path.name} exists; prompt versions are never overwritten"
        )
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def optimize(lm: Any, reflector: Any, budget: int) -> str:
    """Run GEPA from the current prompt version; return the best instructions."""
    calendars = load_calendars()
    reflect_on, select_with = split_for_gepa(load_cases())
    trainset = [to_example(c, calendars[c.calendar]) for c in reflect_on]
    valset = [to_example(c, calendars[c.calendar]) for c in select_with]
    gepa = dspy.GEPA(
        metric=metric,
        reflection_lm=reflector,
        max_metric_calls=budget,  # = parser calls to Gemini; predictable cost
        add_format_failure_as_feedback=True,
        num_threads=1,  # one call at a time: gentler on the rate limit
        seed=0,
    )
    program = ParserProgram(load_instructions(PROMPT_VERSION))
    with dspy.context(lm=lm, adapter=dspy.XMLAdapter(use_json_adapter_fallback=False)):
        optimized = gepa.compile(program, trainset=trainset, valset=valset)
    return str(optimized.parse.signature.instructions)


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--budget", type=int, default=150, help="max parser calls")
    args.add_argument("--reflection-model", default=None, help="default: PLANNER_MODEL")
    options = args.parse_args()

    load_dotenv()
    instructions = optimize(
        parser_lm(model_name(), retries=8),
        reflection_lm(options.reflection_model),
        options.budget,
    )
    path = save_instructions(instructions, next_version())
    version = path.stem.removeprefix("parser_")
    command = "uv run python -m planner.evals.run --baseline parser_solver --split test"
    print(f"saved {path}\nNext: compare v1 and {version} on the test split:")
    print(f"  {command}\n  {command} --prompt {version}")


if __name__ == "__main__":
    main()
