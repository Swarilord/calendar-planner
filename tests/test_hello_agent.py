"""Tests for the hello agent's time tool. No LLM is called."""

from datetime import UTC, datetime

import pytest

from experiments.hello_agent.agent import describe_time, get_now


def test_winter_time_is_utc_plus_1() -> None:
    result = describe_time(datetime(2026, 1, 15, 12, 0, tzinfo=UTC))
    assert result["zurich"] == "2026-01-15T13:00+01:00"
    assert result["timezone_abbreviation"] == "CET"


def test_summer_time_is_utc_plus_2() -> None:
    result = describe_time(datetime(2026, 7, 15, 12, 0, tzinfo=UTC))
    assert result["zurich"] == "2026-07-15T14:00+02:00"
    assert result["timezone_abbreviation"] == "CEST"


@pytest.mark.parametrize(
    ("utc_hour", "utc_minute", "expected_zurich"),
    [
        # Spring forward on 2026-03-29: 01:00 UTC is when 02:00 local becomes 03:00.
        (0, 59, "2026-03-29T01:59+01:00"),
        (1, 0, "2026-03-29T03:00+02:00"),
    ],
)
def test_spring_forward(utc_hour: int, utc_minute: int, expected_zurich: str) -> None:
    moment = datetime(2026, 3, 29, utc_hour, utc_minute, tzinfo=UTC)
    assert describe_time(moment)["zurich"] == expected_zurich


@pytest.mark.parametrize(
    ("utc_hour", "expected_zurich"),
    [
        # Fall back on 2026-10-25: local 02:00-03:00 happens twice.
        (0, "2026-10-25T02:30+02:00"),
        (1, "2026-10-25T02:30+01:00"),
    ],
)
def test_fall_back_hour_happens_twice(utc_hour: int, expected_zurich: str) -> None:
    moment = datetime(2026, 10, 25, utc_hour, 30, tzinfo=UTC)
    assert describe_time(moment)["zurich"] == expected_zurich


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        describe_time(datetime(2026, 1, 15, 12, 0))


def test_get_now_returns_success() -> None:
    assert get_now()["status"] == "success"
