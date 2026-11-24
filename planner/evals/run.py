"""Run a baseline on the eval set, save every outcome, print the summary.

Run:  uv run python -m planner.evals.run --baseline parser_solver --split train
      (--baseline direct, --split test|all, --limit 5, --pause 6,
       PLANNER_MODEL=... to switch model)
"""

import argparse
import json
import time
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from planner.calendar.models import Event
from planner.evals.baselines import (
    Baseline,
    DirectBaseline,
    Outcome,
    ParserSolverBaseline,
)
from planner.evals.dataset import EVALS_DIR, EvalCase, load_calendars, load_cases
from planner.llm import model_name, parser_lm

RESULTS_DIR = EVALS_DIR / "results"


def run_eval(
    baseline: Baseline,
    cases: Sequence[EvalCase],
    calendars: dict[str, list[Event]],
    progress: Callable[[str], None] = print,
    max_outages_in_a_row: int = 3,
    pause_s: float = 0.0,
) -> list[Outcome]:
    """Run every case; stop early if Gemini keeps failing (quota, outage).

    pause_s waits between cases, to stay under a requests-per-minute quota.
    """
    outcomes: list[Outcome] = []
    outages = 0
    for index, case in enumerate(cases):
        if index and pause_s:
            time.sleep(pause_s)
        outcome = baseline.run(case, calendars[case.calendar])
        outcomes.append(outcome)
        verdict = "ok" if succeeded(outcome, case) else (outcome.error or "wrong")
        progress(f"{case.id} {outcome.seconds:5.1f}s {verdict[:70]}")
        outages = outages + 1 if _unavailable(outcome) else 0
        if outages == max_outages_in_a_row:
            progress(f"stopped: {outages} outages in a row (quota or overload?)")
            break
    return outcomes


def _unavailable(outcome: Outcome) -> bool:
    return (outcome.error or "").startswith("unavailable")


def succeeded(outcome: Outcome, case: EvalCase) -> bool:
    """The user got what they needed: the right "impossible", or a valid plan."""
    if outcome.claimed_feasible is None:
        return False
    if not case.expect_feasible:
        return outcome.claimed_feasible is False
    return outcome.claimed_feasible and not outcome.violations


def summarize(outcomes: Sequence[Outcome], cases: Sequence[EvalCase]) -> dict[str, Any]:
    by_id = {c.id: c for c in cases}
    # An outage says nothing about quality: count it, but leave it out of rates.
    answered = [o for o in outcomes if not _unavailable(o)]
    parsed = [o.parse for o in answered if o.parse is not None]
    n = len(answered)
    return {
        "cases": len(outcomes),
        "unavailable": len(outcomes) - n,
        "success_rate": _rate(sum(succeeded(o, by_id[o.case_id]) for o in answered), n),
        "feasibility_accuracy": _rate(
            sum(
                o.claimed_feasible == by_id[o.case_id].expect_feasible for o in answered
            ),
            n,
        ),
        "invalid_output_rate": _rate(
            sum((o.error or "").startswith("invalid") for o in answered), n
        ),
        "parse_exact_rate": _rate(sum(p.exact for p in parsed), len(parsed))
        if parsed
        else None,
        "parse_mistakes": dict(Counter(m.value for p in parsed for m in p.mistakes)),
        "violations": dict(
            Counter(v.kind.value for o in answered for v in o.violations)
        ),
        "mean_seconds": _rate(sum(o.seconds for o in outcomes), len(outcomes)),
    }


def save(
    outcomes: Sequence[Outcome],
    summary: dict[str, Any],
    split: str,
    directory: Path = RESULTS_DIR,
) -> Path:
    first = outcomes[0]
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    model = first.model.replace("/", "_")
    path = directory / f"{stamp}_{first.baseline}_{model}_{split}.json"
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "baseline": first.baseline,
        "model": first.model,
        "prompt_version": first.prompt_version,
        "split": split,
        "summary": summary,
        "outcomes": [_outcome_json(o) for o in outcomes],
    }
    path.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    return path


def _outcome_json(o: Outcome) -> dict[str, Any]:
    return {
        "case_id": o.case_id,
        "seconds": o.seconds,
        "claimed_feasible": o.claimed_feasible,
        "error": o.error,
        "schedule": o.schedule.model_dump(mode="json") if o.schedule else None,
        "violations": [v.model_dump(mode="json") for v in o.violations],
        "parse_findings": (
            [{"mistake": f.mistake.value, "detail": f.detail} for f in o.parse.findings]
            if o.parse
            else None
        ),
    }


def _rate(part: float, whole: int) -> float:
    return round(part / whole, 3) if whole else 0.0


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--baseline", choices=["parser_solver", "direct"], required=True)
    args.add_argument("--split", choices=["train", "test", "all"], default="train")
    args.add_argument("--limit", type=int, default=None)
    args.add_argument("--prompt", default="v1", help="parser prompt version (B only)")
    args.add_argument(
        "--pause", type=float, default=0.0, help="seconds between cases (free quota)"
    )
    options = args.parse_args()

    load_dotenv()
    cases = [c for c in load_cases() if options.split in ("all", c.split)]
    cases = cases[: options.limit]
    lm = parser_lm(model_name())
    baseline: Baseline = (
        ParserSolverBaseline(lm, options.prompt)
        if options.baseline == "parser_solver"
        else DirectBaseline(lm)
    )
    outcomes = run_eval(baseline, cases, load_calendars(), pause_s=options.pause)
    if all(_unavailable(o) for o in outcomes):
        print("Every case was unavailable: nothing saved. Try later or another model.")
        return
    summary = summarize(outcomes, cases)
    path = save(outcomes, summary, options.split)
    print(json.dumps(summary, indent=1))
    print(f"saved to {path}")


if __name__ == "__main__":
    main()
