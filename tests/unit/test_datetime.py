from datetime import UTC, datetime, timedelta, timezone

import pytest

from ocpp_sdk import datetime as odt
from ocpp_sdk.errors import ValidationError


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2025-01-02T03:04:05Z", datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)),
        ("2025-01-02t03:04:05z", datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)),
        ("2025-01-02T03:04:05", datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)),
        ("2025-01-02T03:04:05.123Z", datetime(2025, 1, 2, 3, 4, 5, 123000, tzinfo=UTC)),
        ("2025-01-02T03:04:05.1234567Z", datetime(2025, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)),
        ("2025-01-02T03:04:05.5", datetime(2025, 1, 2, 3, 4, 5, 500000, tzinfo=UTC)),
        ("2025-01-02T03:04:05+01:00", datetime(2025, 1, 2, 2, 4, 5, tzinfo=UTC)),
        ("2025-01-02T03:04:05-05:30", datetime(2025, 1, 2, 8, 34, 5, tzinfo=UTC)),
    ],
)
def test_parse_accepts(text: str, expected: datetime) -> None:
    parsed = odt.parse(text)
    assert parsed == expected
    assert parsed.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "2025-01-02",
        "20250102T030405Z",
        "2025-01-02 03:04:05Z",
        "2025-13-02T03:04:05Z",
        "2025-02-30T03:04:05Z",
        "2025-01-02T24:00:00Z",
        "2025-01-02T03:04:60Z",
        "2025-01-02T03:04:05+24:00",
        "2025-01-02T03:04:05+01:60",
        "2025-01-02T03:04:05+0100",
        "0001-01-01T00:00:00+05:00",
        "٢٠٢٥-01-02T03:04:05Z",
    ],
)
def test_parse_rejects(text: str) -> None:
    with pytest.raises(ValidationError):
        odt.parse(text)


def test_parse_rejects_non_string() -> None:
    with pytest.raises(ValidationError):
        odt.parse(123)  # type: ignore[arg-type]


def test_format_whole_seconds_and_millis() -> None:
    assert odt.format(datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)) == "2025-01-02T03:04:05Z"
    assert (
        odt.format(datetime(2025, 1, 2, 3, 4, 5, 120000, tzinfo=UTC)) == "2025-01-02T03:04:05.120Z"
    )
    assert odt.format(datetime(2025, 1, 2, 3, 4, 5, 1999, tzinfo=UTC)) == "2025-01-02T03:04:05.001Z"


def test_format_converts_to_utc() -> None:
    tz = timezone(timedelta(hours=2))
    assert odt.format(datetime(2025, 1, 2, 3, 4, 5, tzinfo=tz)) == "2025-01-02T01:04:05Z"


def test_format_rejects_naive() -> None:
    with pytest.raises(ValidationError, match="naive"):
        odt.format(datetime(2025, 1, 2, 3, 4, 5))


def test_round_trip() -> None:
    value = datetime(2025, 6, 7, 8, 9, 10, 456000, tzinfo=UTC)
    assert odt.parse(odt.format(value)) == value
