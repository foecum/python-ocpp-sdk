"""Exception hierarchy and CALLERROR code sets.

Example:
    >>> from ocpp_sdk.errors import CallError, ErrorCodeV2
    >>> raise CallError(ErrorCodeV2.NOT_SUPPORTED, "no such feature")  # doctest: +SKIP
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from ocpp_sdk.versions import Version


class OCPPError(Exception):
    """Base class of every exception raised by this SDK."""


class CallTimeoutError(OCPPError):
    """No response arrived within the response timeout."""


class NotConnectedError(OCPPError):
    """The connection is closed or was lost; nothing is queued or retried."""


class QueueFullError(OCPPError):
    """The outgoing call queue is full."""


class ValidationError(OCPPError):
    """A message failed validation, on send or on receive.

    Attributes:
        issues: One ``{"field": ..., "type": ...}`` entry per problem found.
    """

    def __init__(self, message: str, *, issues: Sequence[Mapping[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.issues: list[dict[str, Any]] = [dict(i) for i in issues or ()]


class CallError(OCPPError):
    """A CALLERROR, received from the peer or raised by a handler to send one.

    Example:
        >>> err = CallError("NotSupported", "no such feature")
        >>> str(err)
        'NotSupported: no such feature'
    """

    def __init__(
        self,
        code: str,
        description: str = "",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {description}" if description else code)
        self.code = str(code)
        self.description = description
        self.details: dict[str, Any] = dict(details or {})


class ErrorCodeV16(StrEnum):
    """CALLERROR codes of OCPP 1.6 (note the spec's spelling of ``Occurence``)."""

    NOT_IMPLEMENTED = "NotImplemented"
    NOT_SUPPORTED = "NotSupported"
    INTERNAL_ERROR = "InternalError"
    PROTOCOL_ERROR = "ProtocolError"
    SECURITY_ERROR = "SecurityError"
    FORMATION_VIOLATION = "FormationViolation"
    PROPERTY_CONSTRAINT_VIOLATION = "PropertyConstraintViolation"
    OCCURENCE_CONSTRAINT_VIOLATION = "OccurenceConstraintViolation"
    TYPE_CONSTRAINT_VIOLATION = "TypeConstraintViolation"
    GENERIC_ERROR = "GenericError"


class ErrorCodeV2(StrEnum):
    """CALLERROR codes of OCPP 2.0.1 and 2.1."""

    FORMAT_VIOLATION = "FormatViolation"
    GENERIC_ERROR = "GenericError"
    INTERNAL_ERROR = "InternalError"
    MESSAGE_TYPE_NOT_SUPPORTED = "MessageTypeNotSupported"
    NOT_IMPLEMENTED = "NotImplemented"
    NOT_SUPPORTED = "NotSupported"
    OCCURRENCE_CONSTRAINT_VIOLATION = "OccurrenceConstraintViolation"
    PROPERTY_CONSTRAINT_VIOLATION = "PropertyConstraintViolation"
    PROTOCOL_ERROR = "ProtocolError"
    RPC_FRAMEWORK_ERROR = "RpcFrameworkError"
    SECURITY_ERROR = "SecurityError"
    TYPE_CONSTRAINT_VIOLATION = "TypeConstraintViolation"


V16_ERROR_CODES: frozenset[str] = frozenset(c.value for c in ErrorCodeV16)
V2_ERROR_CODES: frozenset[str] = frozenset(c.value for c in ErrorCodeV2)

_TO_V16 = {
    ErrorCodeV2.FORMAT_VIOLATION.value: ErrorCodeV16.FORMATION_VIOLATION.value,
    ErrorCodeV2.OCCURRENCE_CONSTRAINT_VIOLATION.value: (
        ErrorCodeV16.OCCURENCE_CONSTRAINT_VIOLATION.value
    ),
}
_TO_V2 = {v: k for k, v in _TO_V16.items()}


def error_codes(version: Version) -> frozenset[str]:
    """Return the CALLERROR codes valid for ``version``."""
    return V16_ERROR_CODES if version is Version.OCPP16 else V2_ERROR_CODES


def code_for_version(code: str, version: Version) -> str:
    """Return ``code`` spelled as ``version`` spells it.

    The 1.6 and 2.x spellings of the two renamed codes are translated either
    way; a code the version does not have becomes ``GenericError``.

    Example:
        >>> code_for_version("FormatViolation", Version.OCPP16)
        'FormationViolation'
        >>> code_for_version("RpcFrameworkError", Version.OCPP16)
        'GenericError'
    """
    mapping = _TO_V16 if version is Version.OCPP16 else _TO_V2
    code = mapping.get(code, code)
    return code if code in error_codes(version) else "GenericError"
