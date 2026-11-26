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


def sample(spec: dict[str, Any], defs: dict[str, Any]) -> Any:
    """A value that satisfies ``spec`` with all optional properties set."""
    spec = resolve(spec, defs)
    if "enum" in spec:
        return spec["enum"][0]
    kind = spec.get("type")
    if kind == "object":
        value = {name: sample(sub, defs) for name, sub in spec.get("properties", {}).items()}
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
        return max(1, int(spec.get("minimum", 1)))
    if kind == "number":
        return 1.5
    if kind == "boolean":
        return True
    return "x"  # no type: any JSON value


def load(schema_dir: Path, stem: str) -> tuple[dict[str, Any], Any]:
    """The schema file ``stem`` and a full sample payload for it."""
    schema: dict[str, Any] = json.loads((schema_dir / f"{stem}.json").read_text())
    return schema, sample(schema, schema.get("definitions", {}))
