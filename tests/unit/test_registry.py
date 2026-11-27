from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from ocpp_sdk.errors import CallError, ValidationError
from ocpp_sdk.ocppj.registry import Registry
from ocpp_sdk.versions import Version
from tests.unit.ocppj_models import (
    EchoRequest,
    EchoResponse,
    HeartbeatRequest,
    HeartbeatResponse,
)

EMPTY: dict[str, Any] = {}


def make(version: Version = Version.OCPP201) -> Registry:
    registry = Registry(version)
    registry.register(HeartbeatRequest, HeartbeatResponse)
    registry.register(EchoRequest, EchoResponse)
    return registry


def test_lookup() -> None:
    registry = make()
    assert registry.version is Version.OCPP201
    assert registry.actions() == {"Heartbeat", "Echo"}
    assert "Echo" in registry and "Unknown" not in registry
    assert registry.request_type("Echo") is EchoRequest
    assert registry.response_type("Echo") is EchoResponse


def test_register_errors() -> None:
    registry = make()
    with pytest.raises(ValueError, match="already registered"):
        registry.register(EchoRequest, EchoResponse)

    class NoAction(BaseModel):
        pass

    with pytest.raises(TypeError, match="no ACTION"):
        registry.register(NoAction, EchoResponse)

    class Other(BaseModel):
        ACTION: ClassVar[str] = "Other"

    with pytest.raises(TypeError, match="differ"):
        registry.register(Other, HeartbeatResponse)


def test_decode_request_ok_uses_aliases_and_ignores_unknown() -> None:
    model = make().decode_request("Echo", {"text": "hi", "count": 2, "unknown": 1})
    assert isinstance(model, EchoRequest)
    assert model.count == 2


def test_unknown_action_is_not_implemented() -> None:
    with pytest.raises(CallError) as info:
        make().decode_request("Nope", {})
    assert info.value.code == "NotImplemented"


@pytest.mark.parametrize(
    ("payload", "v2_code", "field"),
    [
        ({}, "OccurrenceConstraintViolation", "text"),
        ({"text": 5}, "TypeConstraintViolation", "text"),
        ({"text": "x" * 11}, "PropertyConstraintViolation", "text"),
        ({"text": ""}, "PropertyConstraintViolation", "text"),
        ({"text": "a", "count": "x"}, "TypeConstraintViolation", "count"),
        ({"text": "a", "items": []}, "OccurrenceConstraintViolation", "items"),
        ({"text": "a", "items": [1, 2, 3, 4]}, "OccurrenceConstraintViolation", "items"),
        ({"text": "a", "items": ["x"]}, "TypeConstraintViolation", "items.0"),
        ({"text": "a", "when": "yesterday"}, "PropertyConstraintViolation", "when"),
    ],
)
def test_decode_request_error_codes(payload: dict[str, Any], v2_code: str, field: str) -> None:
    with pytest.raises(CallError) as info:
        make().decode_request("Echo", payload)
    assert info.value.code == v2_code
    assert info.value.details["errors"][0]["field"] == field
    assert info.value.description.startswith(field)
    assert "x" * 11 not in info.value.description


def test_decode_request_error_codes_16_spelling() -> None:
    registry = make(Version.OCPP16)
    with pytest.raises(CallError) as info:
        registry.decode_request("Echo", {})
    assert info.value.code == "OccurenceConstraintViolation"


def test_decode_response() -> None:
    model = make().decode_response("Heartbeat", {"currentTime": "2025-01-01T00:00:00Z"})
    assert isinstance(model, HeartbeatResponse)
    with pytest.raises(ValidationError) as info:
        make().decode_response("Heartbeat", {})
    assert info.value.issues == [{"field": "currentTime", "type": "missing"}]


def test_encode_uses_aliases_and_drops_none() -> None:
    registry = make()
    request = EchoRequest(text="hi")
    assert registry.encode(request) == {"text": "hi"}
    full = EchoRequest(text="hi", count=1, when=datetime(2025, 1, 1, tzinfo=UTC))
    assert registry.encode(full) == {"text": "hi", "count": 1, "when": "2025-01-01T00:00:00Z"}
    assert registry.encode(HeartbeatResponse(current_time=datetime(2025, 1, 1, tzinfo=UTC))) == {
        "currentTime": "2025-01-01T00:00:00Z"
    }


def test_encode_validates() -> None:
    bad = EchoRequest.model_construct(text="x" * 50)
    with pytest.raises(ValidationError) as info:
        make().encode(bad)
    assert info.value.issues[0]["field"] == "text"
    many = EchoRequest.model_construct(**EMPTY)
    assert make().encode(HeartbeatRequest()) == {}
    with pytest.raises(ValidationError):
        make().encode(many)
