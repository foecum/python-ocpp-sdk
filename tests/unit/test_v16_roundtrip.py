"""Every OCPP 1.6 message round-trips its sample payloads and satisfies the official schema."""

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from ocpp_sdk.v16 import new_registry

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "v16"
SCHEMAS = ROOT / "docs" / "spec" / "1.6" / "schemas" / "json"
REGISTRY = new_registry()
ACTIONS = sorted(p.stem for p in FIXTURES.glob("*.json"))


def schema(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((SCHEMAS / f"{name}.json").read_text())
    return loaded


def sample(action: str, part: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((FIXTURES / f"{action}.json").read_text())[part]
    return payload


def test_every_registered_action_has_a_fixture() -> None:
    assert sorted(REGISTRY.actions()) == ACTIONS


@pytest.mark.parametrize("action", ACTIONS)
def test_request_round_trips(action: str) -> None:
    payload = sample(action, "request")
    jsonschema.validate(payload, schema(action))
    message = REGISTRY.decode_request(action, payload)
    assert type(message).__name__ == f"{action}Request"
    assert REGISTRY.encode(message) == payload


@pytest.mark.parametrize("action", ACTIONS)
def test_response_round_trips(action: str) -> None:
    payload = sample(action, "response")
    jsonschema.validate(payload, schema(f"{action}Response"))
    message = REGISTRY.decode_response(action, payload)
    assert type(message).__name__ == f"{action}Confirmation"
    assert REGISTRY.encode(message) == payload


@pytest.mark.parametrize("action", ACTIONS)
def test_json_text_round_trips(action: str) -> None:
    """Through ``model_validate_json`` / ``model_dump_json`` as well."""
    for part, model in (
        ("request", REGISTRY.request_type(action)),
        ("response", REGISTRY.response_type(action)),
    ):
        payload = sample(action, part)
        decoded = model.model_validate_json(json.dumps(payload))
        assert json.loads(decoded.model_dump_json(by_alias=True, exclude_none=True)) == payload
