"""Schema mutation tests: break every field of every OCPP 1.6 message in every way the
official schema forbids, and check that the SDK rejects the payload.

The valid sample payloads (``tests/fixtures/v16``) are mutated one change at a time:
a required field removed or set to ``null``; a wrong JSON type; a string over
``maxLength``; an unknown enum value; a malformed date-time or URI; an integer with a
fraction; a number that is not a multiple of 0.1; an array under ``minItems`` (only the
security schemas have one). Removing an optional field must be
accepted. Every mutation that is not about a ``format`` is
also checked against the schema itself, so the test cannot drift into mutating
something the schema allows.
"""

import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from ocpp_sdk.errors import CallError, ValidationError
from ocpp_sdk.v16 import new_registry

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "v16"
SCHEMAS = ROOT / "docs" / "spec" / "1.6" / "schemas" / "json"
REGISTRY = new_registry()
ACTIONS = sorted(REGISTRY.actions())

DELETE = object()
Path_ = tuple[str | int, ...]
Mutation = tuple[str, Path_, Any, bool, bool]  # name, path, new value, must reject, schema agrees


def wrong_values(spec: dict[str, Any]) -> list[Any]:
    """Values of another JSON type than ``spec`` allows."""
    kind = spec.get("type")
    others: dict[str, list[Any]] = {
        "string": [5, True, {"a": 1}, ["x"]],
        "integer": ["5", True, {"a": 1}, [1]],
        "number": ["5", True, {"a": 1}, [1]],
        "boolean": ["true", 1, {"a": 1}, [True]],
        "object": ["x", 5, [{}]],
        "array": ["x", 5, {"a": 1}],
    }
    return others[str(kind)]


# The spec says 0..* where the schema says minItems 1 (AGENTS.md section 4): not rejected.
SPEC_BEATS_SCHEMA = {("GetInstalledCertificateIds", "response", ("certificateHashData",))}


def resolve(spec: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Follow ``$ref: #/definitions/X`` (the security schemas use them)."""
    while "$ref" in spec:
        spec = defs[spec["$ref"].removeprefix("#/definitions/")]
    return spec


def mutations(
    spec: dict[str, Any], value: Any, path: Path_, slot: str, defs: dict[str, Any]
) -> Iterator[Mutation]:
    """Every single change to ``value`` (at ``path``) to be tried, with whether it must fail.

    ``slot`` says what the value is: ``root``, a ``required`` or ``optional`` property, or an
    array ``item``.
    """
    spec = resolve(spec, defs)
    kind = spec.get("type")
    if path:
        if slot == "required":
            yield ("remove required", path, DELETE, True, True)
        if slot == "optional":
            yield ("remove optional", path, DELETE, False, True)
        if slot != "optional":  # a null optional is read as absent, as go-ocpp-sdk does
            yield ("null", path, None, True, True)
        for bad in wrong_values(spec):
            yield (f"wrong type {bad!r}", path, bad, True, True)
    if "enum" in spec:
        yield ("unknown enum value", path, "NotAValue", True, True)
    if kind == "string":
        if "maxLength" in spec:
            yield ("too long", path, "x" * (spec["maxLength"] + 1), True, True)
        if spec.get("format") == "date-time":
            yield ("bad date-time", path, "yesterday", True, False)
        if spec.get("format") == "uri":
            yield ("relative uri", path, "no/scheme/here", True, False)
    if kind == "integer":
        yield ("fraction in integer", path, 1.5, True, True)
    if kind == "number" and spec.get("multipleOf") == 0.1:
        yield ("two decimals", path, 8.25, True, True)
    if kind == "object":
        needed = set(spec.get("required", []))
        for name, sub in spec.get("properties", {}).items():
            if name in value:
                yield from mutations(
                    sub,
                    value[name],
                    (*path, name),
                    "required" if name in needed else "optional",
                    defs,
                )
    if kind == "array":
        if "minItems" in spec:
            yield ("under minItems", path, [], True, True)
        for index, item in enumerate(value):
            yield from mutations(spec["items"], item, (*path, index), "item", defs)


def apply(payload: dict[str, Any], path: Path_, new: Any) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    if not path:
        return result if new is DELETE else new
    node: Any = result
    for step in path[:-1]:
        node = node[step]
    if new is DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = new
    return result


def cases(part: str) -> list[Any]:
    out = []
    for action in ACTIONS:
        schema_name = action if part == "request" else f"{action}Response"
        schema = json.loads((SCHEMAS / f"{schema_name}.json").read_text())
        payload = json.loads((FIXTURES / f"{action}.json").read_text())[part]
        defs = schema.get("definitions", {})
        for name, path, new, reject, schema_agrees in mutations(schema, payload, (), "root", defs):
            if (action, part, path) in SPEC_BEATS_SCHEMA and name == "under minItems":
                reject, schema_agrees = False, False
            mutated = apply(payload, path, new)
            label = f"{action}|{part}|{'.'.join(map(str, path)) or 'root'}|{name}"
            out.append(pytest.param(action, schema, mutated, reject, schema_agrees, id=label))
    return out


def accepts(part: str, action: str, payload: dict[str, Any]) -> bool:
    try:
        if part == "request":
            REGISTRY.decode_request(action, payload)
        else:
            REGISTRY.decode_response(action, payload)
    except (CallError, ValidationError):
        return False
    return True


def check(part: str, action: str, schema: Any, payload: Any, reject: bool, agrees: bool) -> None:
    if agrees:
        schema_valid = jsonschema.Draft4Validator(schema).is_valid(payload)
        assert schema_valid is (not reject), "the mutation does not do what it says"
    assert accepts(part, action, payload) is (not reject)


@pytest.mark.parametrize(("action", "schema", "payload", "reject", "agrees"), cases("request"))
def test_request_mutations(
    action: str, schema: Any, payload: Any, reject: bool, agrees: bool
) -> None:
    check("request", action, schema, payload, reject, agrees)


@pytest.mark.parametrize(("action", "schema", "payload", "reject", "agrees"), cases("response"))
def test_response_mutations(
    action: str, schema: Any, payload: Any, reject: bool, agrees: bool
) -> None:
    check("response", action, schema, payload, reject, agrees)


def test_the_mutations_cover_every_constraint_kind() -> None:
    names = {p.id.split("|")[-1] for part in ("request", "response") for p in cases(part)}
    for expected in (
        "remove required",
        "remove optional",
        "null",
        "unknown enum value",
        "too long",
        "bad date-time",
        "relative uri",
        "fraction in integer",
        "two decimals",
        "under minItems",
    ):
        assert expected in names
