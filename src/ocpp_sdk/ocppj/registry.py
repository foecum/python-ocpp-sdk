"""Action registry: maps an action name to its request and response models.

Models are Pydantic models that carry the action name in an ``ACTION``
class variable (the generated 1.6, 2.0.1 and 2.1 messages do).

Example:
    >>> from typing import ClassVar
    >>> from pydantic import BaseModel
    >>> from ocpp_sdk.ocppj.registry import Registry
    >>> from ocpp_sdk.versions import Version
    >>> class PingRequest(BaseModel):
    ...     ACTION: ClassVar[str] = "Ping"
    >>> class PingResponse(BaseModel):
    ...     ACTION: ClassVar[str] = "Ping"
    >>> registry = Registry(Version.OCPP201)
    >>> registry.register(PingRequest, PingResponse)
    >>> registry.decode_request("Ping", {})
    PingRequest()
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from pydantic_core import ErrorDetails

from ocpp_sdk.errors import CallError, ValidationError, code_for_version
from ocpp_sdk.versions import Version

__all__ = ["Registry"]

_MAX_DESCRIPTION = 255
_MAX_ISSUES = 10


def _action_of(model: type[BaseModel]) -> str:
    action = getattr(model, "ACTION", None)
    if not isinstance(action, str) or not action:
        raise TypeError(f"{model.__name__} has no ACTION class variable")
    return action


def _classify(error_type: str) -> str:
    """Map a Pydantic error type to the (2.x spelling of the) CALLERROR code."""
    if error_type in ("missing", "too_short", "too_long", "ocpp_needed"):
        return "OccurrenceConstraintViolation"
    if error_type.startswith(("datetime", "date", "time")):
        return "PropertyConstraintViolation"
    if error_type.endswith(("_type", "_parsing")) or error_type == "int_from_float":
        return "TypeConstraintViolation"
    return "PropertyConstraintViolation"


def _field(error: ErrorDetails) -> str:
    """The JSON path of an error; rules raised by a model add the field they judge."""
    parts = [str(part) for part in error["loc"]]
    inner = (error.get("ctx") or {}).get("field") if error["type"].startswith("ocpp_") else None
    if isinstance(inner, str):
        parts.append(inner)
    return ".".join(parts) or "payload"


def _errors(exc: PydanticValidationError) -> list[ErrorDetails]:
    return exc.errors(include_url=False, include_input=False)


def _issues(exc: PydanticValidationError) -> list[dict[str, Any]]:
    return [{"field": _field(e), "type": e["type"]} for e in _errors(exc)[:_MAX_ISSUES]]


class Registry:
    """Action → request/response models for one protocol version."""

    def __init__(self, version: Version) -> None:
        self._version = version
        self._requests: dict[str, type[BaseModel]] = {}
        self._responses: dict[str, type[BaseModel]] = {}

    @property
    def version(self) -> Version:
        """The protocol version this registry serves."""
        return self._version

    def register(self, request: type[BaseModel], response: type[BaseModel]) -> None:
        """Register a request/response pair under their shared ``ACTION``."""
        action = _action_of(request)
        if _action_of(response) != action:
            raise TypeError(f"{request.__name__} and {response.__name__} differ in ACTION")
        if action in self._requests:
            raise ValueError(f"action {action!r} is already registered")
        self._requests[action] = request
        self._responses[action] = response

    def actions(self) -> frozenset[str]:
        """All registered action names."""
        return frozenset(self._requests)

    def request_type(self, action: str) -> type[BaseModel]:
        """The request model of ``action`` (``KeyError`` if unknown)."""
        return self._requests[action]

    def response_type(self, action: str) -> type[BaseModel]:
        """The response model of ``action`` (``KeyError`` if unknown)."""
        return self._responses[action]

    def decode_request(self, action: str, payload: dict[str, Any]) -> BaseModel:
        """Validate an incoming CALL payload.

        Raises:
            CallError: Unknown action (``NotImplemented``) or invalid payload
                (the matching constraint-violation code for this version).
        """
        model = self._requests.get(action)
        if model is None:
            raise CallError(
                code_for_version("NotImplemented", self._version),
                f"action {action} is not implemented",
            )
        try:
            return model.model_validate(payload)
        except PydanticValidationError as exc:
            first = _errors(exc)[0]
            description = f"{_field(first)}: {first['msg']}"[:_MAX_DESCRIPTION]
            raise CallError(
                code_for_version(_classify(first["type"]), self._version),
                description,
                {"errors": _issues(exc)},
            ) from None

    def decode_response(self, action: str, payload: dict[str, Any]) -> BaseModel:
        """Validate an incoming CALLRESULT payload.

        Raises:
            ValidationError: The payload does not match the response model.
        """
        try:
            return self._responses[action].model_validate(payload)
        except PydanticValidationError as exc:
            issues = _issues(exc)
            raise ValidationError(
                f"invalid {action} response: {issues[0]['field']}", issues=issues
            ) from None

    def encode(self, message: BaseModel) -> dict[str, Any]:
        """Validate and serialise a request or response for sending.

        Camel-case aliases are used and absent optionals are left out.

        Raises:
            ValidationError: The message is invalid (e.g. built with
                ``model_construct`` or modified after creation).
        """
        cls = type(message)
        try:
            payload: dict[str, Any] = message.model_dump(
                mode="json", by_alias=True, exclude_none=True
            )
            cls.model_validate(payload)
        except PydanticValidationError as exc:
            issues = _issues(exc)
            raise ValidationError(
                f"invalid {cls.__name__}: {issues[0]['field']}", issues=issues
            ) from None
        return payload
