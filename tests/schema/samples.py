"""Builds a full valid payload (every optional field present) from an official JSON schema."""

import json
from pathlib import Path
from typing import Any

STAMP = "2025-03-14T09:26:53Z"


def resolve(spec: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Follow ``$ref: #/definitions/X``."""
    while "$ref" in spec:
        spec = defs[spec["$ref"].removeprefix("#/definitions/")]
    return spec


#: Values the spec text requires for some fields (24h times, full dates).
NAMED = {
    "startTimeOfDay": "07:30",
    "endTimeOfDay": "21:45",
    "validFromDate": "2025-01-02",
    "validToDate": "2025-12-31",
}
#: Arrays that the spec text wants to hold at least two coordinates.
TWO_POINTS = {"v2xFreqWattCurve", "v2xSignalWattCurve"}


def _named(name: str, spec: dict[str, Any], defs: dict[str, Any]) -> Any:
    if name in NAMED:
        return NAMED[name]
    value = sample(spec, defs)
    if name in TWO_POINTS:
        return value * 2
    return value


def sample(spec: dict[str, Any], defs: dict[str, Any]) -> Any:
    """A value that satisfies ``spec`` with all optional properties set."""
    spec = resolve(spec, defs)
    if "enum" in spec:
        return spec["enum"][0]
    kind = spec.get("type")
    if kind == "object":
        value = {name: _named(name, sub, defs) for name, sub in spec.get("properties", {}).items()}
        if "chargingProfilePurpose" in value:  # spec text: transactionId only with TxProfile
            value["chargingProfilePurpose"] = "TxProfile"
        return value
    if kind == "array":
        return [sample(spec["items"], defs)]
    if kind == "string":
        if spec.get("format") == "date-time":
            return STAMP
        return "x" * min(spec.get("maxLength", 4), 4)
    if kind == "integer":
        return int(min(max(1, spec.get("minimum", 1)), spec.get("maximum", 10**9)))
    if kind == "number":
        low, high = spec.get("minimum", -1e9), spec.get("maximum", 1e9)
        return float(min(max(1.5, low), high))
    if kind == "boolean":
        return True
    return "x"  # no type: any JSON value


def load(schema_dir: Path, stem: str) -> tuple[dict[str, Any], Any]:
    """The schema file ``stem`` and a full sample payload for it."""
    schema: dict[str, Any] = json.loads((schema_dir / f"{stem}.json").read_text())
    return schema, sample(schema, schema.get("definitions", {}))
