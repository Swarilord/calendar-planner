"""PlanRequest: the parser's typed output, and the solver's input.

The schema rejects requests that are nonsense on any calendar (a negative
duration, a horizon that ends before it starts). Requests that are only
impossible on a particular calendar are left to the solver, which explains why.
"""

from datetime import time
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, PositiveInt, field_validator, model_validator

from planner.common import Schema, UtcDatetime


class Task(Schema):
    """One piece of work to schedule, e.g. "Analysis sheet, 4h, due Thursday"."""

    name: str = Field(min_length=1)
    duration_min: PositiveInt
    deadline: UtcDatetime
    earliest_start: UtcDatetime | None = None
    min_block_min: PositiveInt = 30  # no study blocks shorter than this
    max_block_min: PositiveInt | None = None  # e.g. at most 2h in one sitting

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if self.earliest_start is not None and self.earliest_start >= self.deadline:
            raise ValueError("earliest_start must be before deadline")
        if self.max_block_min is not None and self.max_block_min < self.min_block_min:
            raise ValueError("max_block_min must be at least min_block_min")
        return self


class Window(Schema):
    """A time range, e.g. "keep Wednesday evening free"."""

    start: UtcDatetime
    end: UtcDatetime

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class PlanRequest(Schema):
    """Everything the solver needs to plan, apart from the existing events."""

    horizon_start: UtcDatetime
    horizon_end: UtcDatetime
    tasks: list[Task] = Field(min_length=1)
    blocked: list[Window] = []  # Pydantic copies this default, so it is safe
    # Times of day are wall-clock times in `timezone`, not UTC:
    # "nothing before 9" means 9:00 in Zurich in both summer and winter.
    day_start: time | None = None
    day_end: time | None = None
    max_work_min_per_day: PositiveInt | None = None
    timezone: str = "Europe/Zurich"

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone: {value!r}") from None
        return value

    @field_validator("day_start", "day_end")
    @classmethod
    def _naive_time_of_day(cls, value: time | None) -> time | None:
        if value is not None and value.tzinfo is not None:
            raise ValueError("day_start/day_end are local times without a timezone")
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if self.horizon_end <= self.horizon_start:
            raise ValueError("horizon_end must be after horizon_start")
        names = [task.name for task in self.tasks]
        if len(names) != len(set(names)):
            # Scheduled blocks refer to their task by name.
            raise ValueError("task names must be unique")
        if (
            self.day_start is not None
            and self.day_end is not None
            and self.day_end <= self.day_start
        ):
            raise ValueError("day_end must be after day_start")
        return self
