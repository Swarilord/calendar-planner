"""Tests for the PlanRequest schemas (the parser's output)."""

from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from planner.parser.schemas import PlanRequest, Task, Window

ZURICH = ZoneInfo("Europe/Zurich")


def zurich(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=ZURICH)


def example_request(**overrides: Any) -> PlanRequest:
    """The brief's example 1, as the parser should produce it (week of 23 Nov)."""
    fields: dict[str, Any] = {
        "horizon_start": zurich(23, 0),
        "horizon_end": zurich(30, 0),
        "tasks": [
            {
                "name": "Analysis sheet",
                "duration_min": 240,
                "deadline": zurich(26, 23, 59),
            },
            {"name": "Linear Algebra", "duration_min": 180, "deadline": zurich(27, 12)},
        ],
        "blocked": [{"start": zurich(25, 18), "end": zurich(25, 23, 59)}],
        "day_start": time(9, 0),
    }
    fields.update(overrides)
    return PlanRequest.model_validate(fields)


def test_brief_example_is_valid() -> None:
    request = example_request()
    assert request.tasks[0].deadline == datetime(2026, 11, 26, 22, 59, tzinfo=UTC)
    assert request.day_start == time(9, 0)  # stays a local time of day
    assert request.timezone == "Europe/Zurich"


def test_json_round_trip() -> None:
    # The parser's output arrives as JSON, so it must survive JSON both ways.
    request = example_request()
    assert PlanRequest.model_validate_json(request.model_dump_json()) == request


# --- Task ---


def make_task(**overrides: Any) -> Task:
    fields: dict[str, Any] = {
        "name": "Study",
        "duration_min": 60,
        "deadline": zurich(26, 12),
    }
    fields.update(overrides)
    return Task.model_validate(fields)


@pytest.mark.parametrize("duration", [0, -60])
def test_duration_must_be_positive(duration: int) -> None:
    with pytest.raises(ValidationError, match="greater than 0"):
        make_task(duration_min=duration)


def test_duration_must_be_minutes_not_text() -> None:
    with pytest.raises(ValidationError):
        make_task(duration_min="4h")


@pytest.mark.parametrize("hour", [12, 13])  # equal to and after the deadline
def test_earliest_start_must_be_before_deadline(hour: int) -> None:
    with pytest.raises(ValidationError, match="earliest_start must be before"):
        make_task(earliest_start=zurich(26, hour))


def test_max_block_below_min_block_is_rejected() -> None:
    with pytest.raises(ValidationError, match="max_block_min must be at least"):
        make_task(min_block_min=60, max_block_min=30)


def test_task_defaults() -> None:
    task = make_task()
    assert (task.min_block_min, task.max_block_min, task.earliest_start) == (
        30,
        None,
        None,
    )


# --- Window ---


def test_window_end_must_be_after_start() -> None:
    with pytest.raises(ValidationError, match="end must be after start"):
        Window(start=zurich(25, 18), end=zurich(25, 18))


# --- PlanRequest ---


def test_needs_at_least_one_task() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        example_request(tasks=[])


def test_horizon_must_not_be_backwards() -> None:
    with pytest.raises(ValidationError, match="horizon_end must be after"):
        example_request(horizon_end=zurich(22, 0))


def test_day_end_must_be_after_day_start() -> None:
    with pytest.raises(ValidationError, match="day_end must be after day_start"):
        example_request(day_start=time(18, 0), day_end=time(9, 0))


def test_day_start_with_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError, match="local times"):
        example_request(day_start=time(9, 0, tzinfo=UTC))


@pytest.mark.parametrize("tz", ["Europe/Zurch", "CEST", ""])
def test_unknown_timezone_is_rejected(tz: str) -> None:
    with pytest.raises(ValidationError, match="unknown timezone"):
        example_request(timezone=tz)


def test_blocked_default_is_not_shared() -> None:
    # A classic Python trap: a [] default shared by every instance.
    without_blocked = example_request().model_dump(exclude={"blocked"})
    a = PlanRequest.model_validate(without_blocked)
    b = PlanRequest.model_validate(without_blocked)
    assert a.blocked == [] and b.blocked == []
    assert a.blocked is not b.blocked


def test_task_names_must_be_unique() -> None:
    task = {"name": "Study", "duration_min": 60, "deadline": zurich(26, 12)}
    with pytest.raises(ValidationError, match="task names must be unique"):
        example_request(tasks=[task, task])


@pytest.mark.parametrize("field", ["duration_min", "min_block_min", "max_block_min"])
def test_lengths_must_be_whole_15_minute_slots(field: str) -> None:
    with pytest.raises(ValidationError, match="multiple of 15"):
        make_task(**{field: 50})
