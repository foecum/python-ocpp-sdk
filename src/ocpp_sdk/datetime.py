"""The one date-time parser and formatter, shared by every OCPP version.

Sending: UTC with ``Z``, whole seconds, or milliseconds when the value has a
fraction. Receiving: RFC 3339 with or without fractional seconds, ``Z`` or an
offset, or no zone at all (taken as UTC).

Example:
    >>> from ocpp_sdk import datetime as ocpp_datetime
    >>> ocpp_datetime.format(ocpp_datetime.parse("2025-01-02T03:04:05+01:00"))
    '2025-01-02T02:04:05Z'
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

from ocpp_sdk.errors import ValidationError

__all__ = ["format", "parse"]

_PATTERN = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})"
    r"(?:\.([0-9]+))?(?:([Zz])|([+-])([0-9]{2}):([0-9]{2}))?"
)


def parse(value: str) -> datetime:
    """Parse an OCPP date-time into an aware UTC ``datetime``.

    Raises:
        ValidationError: ``value`` is not an RFC 3339 date-time.
    """
    match = _PATTERN.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValidationError(f"invalid date-time {value!r}")
    year, month, day, hour, minute, second, frac, _z, sign, off_h, off_m = match.groups()
    try:
        micro = int((frac + "000000")[:6]) if frac else 0
        tz = UTC
        if sign:
            if int(off_h) > 23 or int(off_m) > 59:
                raise ValueError("offset out of range")
            delta = timedelta(hours=int(off_h), minutes=int(off_m))
            tz = timezone(-delta if sign == "-" else delta)
        parsed = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second), micro, tz
        )
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise ValidationError(f"invalid date-time {value!r}") from exc


def format(value: datetime) -> str:
    """Format an aware ``datetime`` as UTC, with milliseconds only if it has a fraction.

    Raises:
        ValidationError: ``value`` is a naive ``datetime`` (no time zone).
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError("naive datetime rejected: attach a time zone (e.g. tzinfo=UTC)")
    utc = value.astimezone(UTC)
    text = utc.strftime("%Y-%m-%dT%H:%M:%S")
    if utc.microsecond:
        text += f".{utc.microsecond // 1000:03d}"
    return text + "Z"
