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

import base64
import binascii
import re
from collections.abc import Callable
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
    "Base64",
    "DateTime",
    "Hex",
    "HexBytes",
    "Number",
    "OCPPModel",
    "OneDecimal",
    "PemCertificate",
    "PemCertificates",
    "PemCsr",
    "full_date_ok",
    "needed_error",
    "rule_error",
    "time_of_day_ok",
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


_PEM_BLOCK = re.compile(r"-----BEGIN ([A-Z0-9 ]+)-----(.*?)-----END \1-----", re.DOTALL)
_PEM_BODY = re.compile(r"[A-Za-z0-9+/=\s]*")


def _pem(types: tuple[str, ...], max_blocks: int | None) -> Callable[[str], str]:
    """A check for text made of PEM blocks of the given types (the contents are not parsed)."""

    def check(value: str) -> str:
        blocks = list(_PEM_BLOCK.finditer(value))
        if not blocks:
            raise PydanticCustomError("ocpp_rule", "must be PEM encoded")
        for block in blocks:
            if block.group(1) not in types:
                raise PydanticCustomError(
                    "ocpp_rule",
                    "unexpected PEM block {kind}, want {want}",
                    {"kind": block.group(1), "want": " or ".join(types)},
                )
            if not _PEM_BODY.fullmatch(block.group(2)):
                raise PydanticCustomError("ocpp_rule", "a PEM block is not Base64 text")
        if max_blocks is not None and len(blocks) > max_blocks:
            raise PydanticCustomError(
                "ocpp_rule",
                "contains {n} PEM blocks, at most {max} allowed",
                {"n": len(blocks), "max": max_blocks},
            )
        if _PEM_BLOCK.sub("", value).strip():
            raise PydanticCustomError("ocpp_rule", "contains data outside the PEM blocks")
        return value

    return check


PemCertificate = Annotated[str, Strict(), AfterValidator(_pem(("CERTIFICATE",), 1))]
"""One PEM encoded X.509 certificate."""

PemCertificates = Annotated[str, Strict(), AfterValidator(_pem(("CERTIFICATE",), None))]
"""One or more PEM encoded X.509 certificates (a chain)."""

PemCsr = Annotated[
    str, Strict(), AfterValidator(_pem(("CERTIFICATE REQUEST", "NEW CERTIFICATE REQUEST"), 1))
]
"""One PEM encoded PKCS#10 certificate signing request."""


def _check_hex(value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]+", value):
        raise PydanticCustomError("ocpp_rule", "must be hexadecimal")
    return value


def _check_hex_bytes(value: str) -> str:
    _check_hex(value)
    if len(value) % 2:
        raise PydanticCustomError("ocpp_rule", "must have two hexadecimal digits per byte")
    return value


def _check_base64(value: str) -> str:
    try:
        base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise PydanticCustomError("ocpp_rule", "must be Base64 encoded") from None
    return value


Hex = Annotated[str, Strict(), AfterValidator(_check_hex)]
"""A hexadecimal string."""

HexBytes = Annotated[str, Strict(), AfterValidator(_check_hex_bytes)]
"""A hexadecimal string with two digits per byte."""

Base64 = Annotated[str, Strict(), AfterValidator(_check_base64)]
"""A Base64 (standard alphabet, padded) string."""


_TIME_OF_DAY = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")
_FULL_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def time_of_day_ok(value: str) -> bool:
    """Whether ``value`` is ``HH:MM`` in 24h format with leading zeros.

    Example:
        >>> time_of_day_ok("07:30"), time_of_day_ok("7:30"), time_of_day_ok("24:00")
        (True, False, False)
    """
    return _TIME_OF_DAY.fullmatch(value) is not None


def full_date_ok(value: str) -> bool:
    """Whether ``value`` is an RFC 3339 full-date written ``YYYY-MM-DD`` and a real date.

    Example:
        >>> full_date_ok("2025-02-28"), full_date_ok("2025-02-30"), full_date_ok("25-02-28")
        (True, False, False)
    """
    if _FULL_DATE.fullmatch(value) is None:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True
