"""Single-change mutations of a valid payload that the official JSON schema forbids."""

import copy
from collections.abc import Callable, Iterator
from typing import Any

import jsonschema

from tests.schema.samples import resolve

DELETE = object()
Path_ = tuple[str | int, ...]
Mutation = tuple[str, Path_, Any, bool, bool]  # name, path, new value, must reject, schema agrees


def wrong_values(spec: dict[str, Any]) -> list[Any]:
    """Values of another JSON type than ``spec`` allows."""
    others: dict[str, list[Any]] = {
        "string": [5, True, {"a": 1}, ["x"]],
        "integer": ["5", True, {"a": 1}, [1]],
        "number": ["5", True, {"a": 1}, [1]],
        "boolean": ["true", 1, {"a": 1}, [True]],
        "object": ["x", 5, [{}]],
        "array": ["x", 5, {"a": 1}],
    }
    return others.get(str(spec.get("type")), [])


def mutations(
    spec: dict[str, Any], value: Any, path: Path_, slot: str, defs: dict[str, Any]
) -> Iterator[Mutation]:
    """Every single change to ``value`` (at ``path``) to try, with whether it must fail.

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
        if slot != "optional" and kind is not None:  # a null optional is read as absent
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
    if kind in ("integer", "number"):
        if "minimum" in spec:
            yield ("below minimum", path, spec["minimum"] - 1, True, True)
        if "maximum" in spec:
            yield ("above maximum", path, spec["maximum"] + 1, True, True)
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
        if "maxItems" in spec:
            yield ("over maxItems", path, [value[0]] * (spec["maxItems"] + 1), True, True)
        for index, item in enumerate(value):
            yield from mutations(spec["items"], item, (*path, index), "item", defs)


def apply(payload: Any, path: Path_, new: Any) -> Any:
    """A copy of ``payload`` with ``path`` set to ``new`` (or deleted)."""
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


def failures(
    schema: dict[str, Any],
    payload: Any,
    accepts: Callable[[Any], bool],
    overrides: set[tuple[Path_, str]] = frozenset(),  # type: ignore[assignment]
    required_by_spec: frozenset[str] = frozenset(),
) -> list[str]:
    """Run every mutation of ``payload``; return a line for each one the SDK got wrong.

    ``required_by_spec`` names fields the schema leaves optional but a rule of the spec text
    (or its errata) requires in the samples' context.
    """
    wrong: list[str] = []
    defs = schema.get("definitions", {})
    validator = jsonschema.Draft4Validator(schema)
    for name, path, new, reject, schema_agrees in mutations(schema, payload, (), "root", defs):
        if (path, name) in overrides:  # the spec says otherwise (AGENTS.md section 4)
            reject, schema_agrees = False, False
        if name == "remove optional" and path[-1] in required_by_spec:
            reject, schema_agrees = True, False  # optional in the schema, required by a rule
        mutated = apply(payload, path, new)
        label = f"{'.'.join(map(str, path)) or 'root'}: {name}"
        if schema_agrees and validator.is_valid(mutated) is reject:
            wrong.append(f"{label}: the mutation does not do what it says")
        elif accepts(mutated) is reject:
            wrong.append(f"{label}: {'accepted' if reject else 'rejected'}")
    return wrong
