"""Calendar event schemas shared by every CalendarBackend.

All times are timezone-aware and stored in UTC. Naive datetimes are rejected,
because "12:00" without a timezone does not say which moment it is.
"""

from datetime import UTC, datetime
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


# Must carry a timezone on input; converted to UTC after validation.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]


class _Schema(BaseModel):
    """Base for all schemas: immutable, and unknown fields are an error."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class NewEvent(_Schema):
    """An event to be created. The backend assigns the id."""

    title: str = Field(min_length=1)
    start: UtcDatetime
    end: UtcDatetime
    plan_id: str | None = None

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class Event(NewEvent):
    """An event that exists in a calendar."""

    id: str = Field(min_length=1)
    # True only for events this app created. Only those may be edited or deleted.
    created_by_planner: bool = False


class EventChanges(_Schema):
    """Fields to change on an existing event. None means "leave as it is"."""

    title: str | None = Field(default=None, min_length=1)
    start: UtcDatetime | None = None
    end: UtcDatetime | None = None
