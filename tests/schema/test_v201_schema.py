"""OCPP 2.0.1: every message round-trips a full sample built from its official schema, and
every single-field mutation the schema forbids is rejected (see ``mutlib``)."""

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from ocpp_sdk.errors import CallError, ValidationError
from ocpp_sdk.v201 import new_registry
from tests.schema import samples
from tests.schema.mutlib import failures

SCHEMAS = Path(__file__).resolve().parents[2] / "docs" / "spec" / "2.0.1" / "schemas"
REGISTRY = new_registry()
ACTIONS = sorted(REGISTRY.actions())


def accepts(part: str, action: str, payload: Any) -> bool:
    try:
        if part == "request":
            REGISTRY.decode_request(action, payload)
        else:
            REGISTRY.decode_response(action, payload)
    except (CallError, ValidationError):
        return False
    return True


def test_every_schema_is_a_registered_message() -> None:
    stems = {p.stem for p in SCHEMAS.glob("*.json")}
    assert stems == {f"{a}{s}" for a in ACTIONS for s in ("Request", "Response")}


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("part", ["request", "response"])
def test_round_trip(action: str, part: str) -> None:
    schema, payload = samples.load(SCHEMAS, f"{action}{part.capitalize()}")
    jsonschema.validate(payload, schema)
    model = (REGISTRY.request_type if part == "request" else REGISTRY.response_type)(action)
    message = model.model_validate(payload)
    assert REGISTRY.encode(message) == payload
    assert json.loads(message.model_dump_json(by_alias=True, exclude_none=True)) == payload


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("part", ["request", "response"])
def test_mutations(action: str, part: str) -> None:
    schema, payload = samples.load(SCHEMAS, f"{action}{part.capitalize()}")
    wrong = failures(schema, payload, lambda p: accepts(part, action, p))
    assert not wrong, "\n".join(wrong)
