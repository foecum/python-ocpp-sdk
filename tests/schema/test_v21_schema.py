"""OCPP 2.1: every message round-trips a full sample built from its official schema, and
every single-field mutation the schema forbids is rejected (see ``mutlib``)."""

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from ocpp_sdk.errors import CallError, ValidationError
from ocpp_sdk.v21 import new_registry
from tests.schema import samples
from tests.schema.mutlib import failures

SCHEMAS = Path(__file__).resolve().parents[2] / "docs" / "spec" / "2.1" / "schemas"
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


#: Optional in the schemas, required by the 2.1 errata 2026-09 (2.28) and the voltage rule.
REQUIRED_BY_RULE = frozenset({"pctMaxDischargePower", "hv10MinMeanValue", "hv10MinMeanTripDelay"})
ONE_WAY = sorted(a for a in ACTIONS if REGISTRY.is_one_way(a))
TWO_WAY = [a for a in ACTIONS if a not in ONE_WAY]


def stem(action: str, part: str) -> str:
    return action if action in ONE_WAY else f"{action}{part.capitalize()}"


def test_every_schema_is_a_registered_message() -> None:
    stems = {p.stem for p in SCHEMAS.glob("*.json")}
    assert stems == {f"{a}{s}" for a in TWO_WAY for s in ("Request", "Response")} | set(ONE_WAY)
    assert len(ACTIONS) == 91 and ONE_WAY == ["NotifyPeriodicEventStream"]


CASES = [
    (a, p) for a in ACTIONS for p in (["request"] if a in ONE_WAY else ["request", "response"])
]


@pytest.mark.parametrize(("action", "part"), CASES)
def test_round_trip(action: str, part: str) -> None:
    schema, payload = samples.load(SCHEMAS, stem(action, part))
    jsonschema.validate(payload, schema)
    model = (REGISTRY.request_type if part == "request" else REGISTRY.response_type)(action)
    message = model.model_validate(payload)
    assert REGISTRY.encode(message) == payload
    assert json.loads(message.model_dump_json(by_alias=True, exclude_none=True)) == payload


@pytest.mark.parametrize(("action", "part"), CASES)
def test_mutations(action: str, part: str) -> None:
    schema, payload = samples.load(SCHEMAS, stem(action, part))
    wrong = failures(
        schema, payload, lambda p: accepts(part, action, p), required_by_spec=REQUIRED_BY_RULE
    )
    assert not wrong, "\n".join(wrong)
