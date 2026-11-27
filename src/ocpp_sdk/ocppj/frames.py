"""OCPP-J frames: CALL, CALLRESULT and CALLERROR, with parsing and encoding.

Example:
    >>> from ocpp_sdk.ocppj.frames import Call, encode, parse_frame
    >>> from ocpp_sdk.versions import Version
    >>> text = encode(Call("19223201", "Heartbeat", {}))
    >>> text
    '[2,"19223201","Heartbeat",{}]'
    >>> parse_frame(text, Version.OCPP16)
    Call(unique_id='19223201', action='Heartbeat', payload={})
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, NoReturn

from ocpp_sdk.errors import ErrorCodeV2, OCPPError
from ocpp_sdk.versions import Version

__all__ = [
    "CALL",
    "CALL_ERROR",
    "CALL_RESULT",
    "CALL_RESULT_ERROR",
    "MAX_ID_LENGTH",
    "SEND",
    "UNREADABLE_ID",
    "Call",
    "CallErrorFrame",
    "CallResult",
    "CallResultErrorFrame",
    "Frame",
    "FrameError",
    "Send",
    "encode",
    "framework_error_code",
    "parse_frame",
]

CALL = 2
CALL_RESULT = 3
CALL_ERROR = 4
CALL_RESULT_ERROR = 5
SEND = 6
MAX_ID_LENGTH = 36
UNREADABLE_ID = "-1"


@dataclass(frozen=True, slots=True)
class Call:
    """``[2, uniqueId, action, payload]``."""

    unique_id: str
    action: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CallResult:
    """``[3, uniqueId, payload]``."""

    unique_id: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CallErrorFrame:
    """``[4, uniqueId, errorCode, errorDescription, errorDetails]``."""

    unique_id: str
    code: str
    description: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Send:
    """``[6, uniqueId, action, payload]`` (OCPP 2.1): an unconfirmed message, never answered."""

    unique_id: str
    action: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CallResultErrorFrame:
    """``[5, uniqueId, errorCode, errorDescription, errorDetails]`` (OCPP 2.1).

    Sent by the receiver of a CALLRESULT that it cannot accept.
    """

    unique_id: str
    code: str
    description: str = ""
    details: dict[str, Any] = field(default_factory=dict)


Frame = Call | CallResult | CallErrorFrame | Send | CallResultErrorFrame


class FrameError(OCPPError):
    """A received frame could not be understood.

    Attributes:
        code: CALLERROR code to answer with (spelled for the version).
        description: Short description for the CALLERROR.
        unique_id: The frame's message ID, or ``"-1"`` when it was unreadable.
        reply: Whether the peer is answered with a CALLERROR (otherwise the
            frame is only logged and ignored).
        message_type: The frame's message type when it was readable.
    """

    def __init__(
        self,
        code: str,
        description: str,
        *,
        unique_id: str = UNREADABLE_ID,
        reply: bool = True,
        message_type: int | None = None,
    ) -> None:
        super().__init__(f"{code}: {description}")
        self.code = code
        self.description = description
        self.unique_id = unique_id
        self.reply = reply
        self.message_type = message_type


def framework_error_code(version: Version) -> str:
    """Return the code for a frame that is not a valid RPC message."""
    if version is Version.OCPP16:
        return "FormationViolation"
    return ErrorCodeV2.RPC_FRAMEWORK_ERROR.value


def _reject_constant(name: str) -> NoReturn:
    raise ValueError(f"invalid JSON constant {name}")


def _readable_id(value: object) -> str | None:
    if isinstance(value, str) and 0 < len(value) <= MAX_ID_LENGTH:
        return value
    return None


def parse_frame(raw: str, version: Version) -> Frame:
    """Parse one text frame.

    A ``null`` payload is accepted and treated as ``{}``. A CALLERROR with
    only four elements (no details) is accepted too.

    Raises:
        FrameError: The frame is not valid; the exception says how to answer.
    """
    framework = framework_error_code(version)
    try:
        data = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise FrameError(framework, "message is not valid JSON") from None
    if not isinstance(data, list) or len(data) < 2:
        raise FrameError(framework, "message is not a JSON array of at least two elements")
    uid = _readable_id(data[1])
    mtype = data[0]
    if type(mtype) is not int:
        raise FrameError(framework, "message type is not an integer", unique_id=uid or "-1")
    if mtype == CALL:
        return _parse_call(data, uid, framework)
    if mtype == CALL_RESULT:
        return _parse_result(data, uid, framework)
    if mtype == CALL_ERROR:
        return _parse_error(data, uid, framework)
    if version is Version.OCPP21 and mtype == SEND:
        return _parse_send(data, uid, framework)
    if version is Version.OCPP21 and mtype == CALL_RESULT_ERROR:
        return _parse_result_error(data, uid, framework)
    if version is Version.OCPP201:
        raise FrameError(
            ErrorCodeV2.MESSAGE_TYPE_NOT_SUPPORTED.value,
            f"message type {mtype} is not supported",
            unique_id=uid or UNREADABLE_ID,
            message_type=mtype,
        )
    raise FrameError(
        framework,
        f"message type {mtype} is not supported",
        unique_id=uid or UNREADABLE_ID,
        reply=False,
        message_type=mtype,
    )


def _payload(value: object) -> dict[str, Any] | None:
    if value is None:
        return {}
    return value if isinstance(value, dict) else None


def _parse_call(data: list[Any], uid: str | None, framework: str) -> Call:
    if uid is None:
        raise FrameError(
            framework,
            "message id is missing, not a string or longer than 36 characters",
            message_type=CALL,
        )
    if len(data) != 4:
        raise FrameError(framework, "a CALL has four elements", unique_id=uid, message_type=CALL)
    action = data[2]
    if not isinstance(action, str) or not action:
        raise FrameError(
            framework, "action is not a non-empty string", unique_id=uid, message_type=CALL
        )
    payload = _payload(data[3])
    if payload is None:
        raise FrameError(
            framework, "payload is not a JSON object", unique_id=uid, message_type=CALL
        )
    return Call(uid, action, payload)


def _parse_result(data: list[Any], uid: str | None, framework: str) -> CallResult:
    if uid is None:
        raise FrameError(
            framework, "message id is unreadable", reply=False, message_type=CALL_RESULT
        )
    payload = _payload(data[2]) if len(data) == 3 else None
    if payload is None:
        raise FrameError(
            framework,
            "a CALLRESULT is [3, id, object]",
            unique_id=uid,
            reply=False,
            message_type=CALL_RESULT,
        )
    return CallResult(uid, payload)


def _parse_error(data: list[Any], uid: str | None, framework: str) -> CallErrorFrame:
    if uid is None:
        raise FrameError(
            framework, "message id is unreadable", reply=False, message_type=CALL_ERROR
        )
    code = data[2] if len(data) in (4, 5) else None
    description = data[3] if len(data) in (4, 5) else None
    details = _payload(data[4]) if len(data) == 5 else {}
    if not isinstance(code, str) or not isinstance(description, str | None) or details is None:
        raise FrameError(
            framework,
            "a CALLERROR is [4, id, code, description, object]",
            unique_id=uid,
            reply=False,
            message_type=CALL_ERROR,
        )
    return CallErrorFrame(uid, code, description or "", details)


def _parse_send(data: list[Any], uid: str | None, framework: str) -> Send:
    """A SEND is never answered, so every problem is ``reply=False``."""
    action = data[2] if len(data) == 4 else None
    payload = _payload(data[3]) if len(data) == 4 else None
    if uid is None or not isinstance(action, str) or not action or payload is None:
        raise FrameError(
            framework, "a SEND is [6, id, action, object]", reply=False, message_type=SEND
        )
    return Send(uid, action, payload)


def _parse_result_error(data: list[Any], uid: str | None, framework: str) -> CallResultErrorFrame:
    code = data[2] if len(data) in (4, 5) else None
    description = data[3] if len(data) in (4, 5) else None
    details = _payload(data[4]) if len(data) == 5 else {}
    if (
        uid is None
        or not isinstance(code, str)
        or not isinstance(description, str | None)
        or details is None
    ):
        raise FrameError(
            framework,
            "a CALLRESULTERROR is [5, id, code, description, object]",
            reply=False,
            message_type=CALL_RESULT_ERROR,
        )
    return CallResultErrorFrame(uid, code, description or "", details)


def encode(frame: Frame) -> str:
    """Serialise a frame to compact JSON text."""
    items: list[Any]
    if isinstance(frame, Call):
        items = [CALL, frame.unique_id, frame.action, frame.payload]
    elif isinstance(frame, CallResult):
        items = [CALL_RESULT, frame.unique_id, frame.payload]
    elif isinstance(frame, Send):
        items = [SEND, frame.unique_id, frame.action, frame.payload]
    elif isinstance(frame, CallResultErrorFrame):
        items = [CALL_RESULT_ERROR, frame.unique_id, frame.code, frame.description, frame.details]
    else:
        items = [CALL_ERROR, frame.unique_id, frame.code, frame.description, frame.details]
    return json.dumps(items, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
