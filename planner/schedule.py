"""A schedule: the solver's output and the checker's input."""

from typing import Self

from pydantic import Field, model_validator

from planner.common import Schema, UtcDatetime


class ScheduledBlock(Schema):
    """One block of time spent on one task. Times are exact, to the minute."""

    task_name: str = Field(min_length=1)
    start: UtcDatetime
    end: UtcDatetime

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class Schedule(Schema):
    """All blocks proposed for one PlanRequest."""

    blocks: list[ScheduledBlock] = []
