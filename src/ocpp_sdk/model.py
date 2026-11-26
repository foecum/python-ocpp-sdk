"""Base class and field types shared by every generated message model.

Python attribute names are snake_case; the JSON names are the spec's exact
camelCase (the alias is generated). Serialise with ``by_alias=True,
exclude_none=True`` (``Registry.encode`` does) so absent optional fields are not
sent. Unknown properties are ignored when decoding, because real charge points
send extras and rejecting them would break interoperability.

Example:
    >>> from ocpp_sdk.model import DateTime, OCPPModel
    >>> class Reading(OCPPModel):
    ...     taken_at: DateTime
    >>> reading = Reading.model_validate({"takenAt": "2025-01-02T03:04:05Z", "extra": 1})
    >>> reading.model_dump(mode="json", by_alias=True)
    {'takenAt': '2025-01-02T03:04:05Z'}
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    Strict,
)
from pydantic.alias_generators import to_camel
from pydantic_core import PydanticCustomError

from ocpp_sdk import datetime as ocpp_datetime
from ocpp_sdk.errors import ValidationError

__all__ = [
    "AbsoluteURI",
    "DateTime",
    "Number",
    "OCPPModel",
    "OneDecimal",
    "needed_error",
    "rule_error",
]


class OCPPModel(BaseModel):
    """Base of every message and datatype model."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


def rule_error(field: str, reason: str) -> PydanticCustomError:
    """The error for a rule of the spec text that a value breaks.

    ``field`` is the JSON path below the model that raises it (``"a.0.b"``).

    Example:
        >>> rule_error("limit", "must be positive").message()
        'must be positive'
    """
    return PydanticCustomError("ocpp_rule", "{reason}", {"field": field, "reason": reason})


def needed_error(field: str) -> PydanticCustomError:
    """The error for a field the spec text requires under some condition.

    Example:
        >>> needed_error("idTagInfo").message()
        'required here'
    """
    return PydanticCustomError("ocpp_needed", "required here", {"field": field})


def _parse_date_time(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return ocpp_datetime.parse(value)
        except ValidationError as exc:
            raise PydanticCustomError(
                "datetime_parsing", "{reason}", {"reason": str(exc)}
            ) from None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise PydanticCustomError(
                "datetime_naive", "naive datetime rejected: attach a time zone (e.g. tzinfo=UTC)"
            )
        return value.astimezone(UTC)
    raise PydanticCustomError("ocpp_type", "Input should be a datetime or an RFC 3339 string")


DateTime = Annotated[
    datetime,
    BeforeValidator(_parse_date_time),
    PlainSerializer(ocpp_datetime.format, return_type=str, when_used="json"),
]
"""A timestamp: parsed from RFC 3339, sent as UTC with ``Z``. Naive values are rejected."""


def _check_absolute_uri(value: str) -> str:
    if not urlsplit(value).scheme:
        raise PydanticCustomError("ocpp_rule", "must be an absolute URI")
    return value


AbsoluteURI = Annotated[str, Strict(), AfterValidator(_check_absolute_uri)]
"""A string that is an absolute URI (has a scheme such as ``ftp:`` or ``https:``)."""

Number = Annotated[float, Strict(), Field(allow_inf_nan=False)]
"""A JSON number; integers are accepted, ``bool`` and strings are not."""


def _check_one_decimal(value: float) -> float:
    scaled = value * 10
    if abs(scaled - round(scaled)) > 1e-6:
        raise PydanticCustomError("ocpp_rule", "accepts at most one digit fraction")
    return value


OneDecimal = Annotated[Number, AfterValidator(_check_one_decimal)]
"""A number with at most one fractional digit, as charging limits require."""
