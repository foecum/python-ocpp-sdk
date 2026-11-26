"""Base model, date-time, URI, number and rule helpers."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from ocpp_sdk.model import (
    AbsoluteURI,
    DateTime,
    Number,
    OCPPModel,
    OneDecimal,
    needed_error,
    rule_error,
)


class Sample(OCPPModel):
    taken_at: DateTime
    where: AbsoluteURI | None = None
    amount: Number | None = None
    limit: OneDecimal | None = None


def error_types(**payload: Any) -> list[str]:
    with pytest.raises(ValidationError) as info:
        Sample.model_validate(payload)
    return [e["type"] for e in info.value.errors()]


def test_alias_and_extra_properties() -> None:
    s = Sample.model_validate({"takenAt": "2025-01-02T03:04:05Z", "unknown": 1})
    assert s.taken_at == datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert Sample(taken_at=s.taken_at).taken_at == s.taken_at  # populate by name


def test_datetime_serialises_utc_with_z() -> None:
    local = datetime(2025, 1, 2, 5, 4, 5, tzinfo=timezone(timedelta(hours=2)))
    s = Sample(taken_at=local)
    assert s.taken_at.utcoffset() == timedelta(0)
    assert s.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "takenAt": "2025-01-02T03:04:05Z"
    }
    assert s.model_dump()["taken_at"] == datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_datetime_without_zone_in_a_string_is_utc() -> None:
    assert Sample.model_validate({"takenAt": "2025-01-02T03:04:05"}).taken_at.tzinfo == UTC


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("yesterday", "datetime_parsing"),
        (datetime(2025, 1, 2), "datetime_naive"),
        (1700000000, "ocpp_type"),
        (None, "ocpp_type"),
    ],
)
def test_datetime_rejects(value: Any, kind: str) -> None:
    assert error_types(takenAt=value) == [kind]


def test_absolute_uri() -> None:
    ok = Sample.model_validate({"takenAt": "2025-01-02T03:04:05Z", "where": "ftp://h/f"})
    assert ok.where == "ftp://h/f"
    assert error_types(takenAt="2025-01-02T03:04:05Z", where="/relative/path") == ["ocpp_rule"]
    assert error_types(takenAt="2025-01-02T03:04:05Z", where=5) == ["string_type"]


@pytest.mark.parametrize("value", [1, 1.5, 0])
def test_number_accepts_numbers(value: float) -> None:
    assert (
        Sample.model_validate({"takenAt": "2025-01-02T03:04:05Z", "amount": value}).amount == value
    )


@pytest.mark.parametrize("value", ["1", True, float("nan"), float("inf")])
def test_number_rejects_everything_else(value: Any) -> None:
    assert error_types(takenAt="2025-01-02T03:04:05Z", amount=value)


@pytest.mark.parametrize("value", [0, 8, 8.1, -0.3, 22.0, 1234567.8])
def test_one_decimal_accepts(value: float) -> None:
    assert Sample.model_validate({"takenAt": "2025-01-02T03:04:05Z", "limit": value}).limit == value


@pytest.mark.parametrize("value", [8.15, 0.01, -1.234])
def test_one_decimal_rejects(value: float) -> None:
    assert error_types(takenAt="2025-01-02T03:04:05Z", limit=value) == ["ocpp_rule"]


def test_rule_and_needed_errors() -> None:
    rule = rule_error("a.0.b", "must be positive")
    assert (rule.type, rule.message()) == ("ocpp_rule", "must be positive")
    assert rule.context == {"field": "a.0.b", "reason": "must be positive"}
    needed = needed_error("idTagInfo")
    assert (needed.type, needed.message()) == ("ocpp_needed", "required here")
    assert needed.context == {"field": "idTagInfo"}
