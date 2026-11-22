"""Building blocks shared by all schemas: a strict base class and a UTC time type."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


# Must carry a timezone on input; converted to UTC after validation.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]


class Schema(BaseModel):
    """Base for all schemas: immutable, and unknown fields are an error."""

    model_config = ConfigDict(frozen=True, extra="forbid")
