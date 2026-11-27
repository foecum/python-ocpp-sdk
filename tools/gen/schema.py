"""Reads the official JSON schemas into a small model the emitter renders.

Every anything the profile tables do not account for is an error, so a schema
change or a missing table entry stops the generator instead of producing
something wrong.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic.alias_generators import to_camel

from tools.gen.profiles import Profile

ROOT = Path(__file__).resolve().parents[2]

_DOC_KEYS = ("javaType", "definitions", "description", "comment")
_IGNORED = {"$schema", "id", "$id", "title", "additionalProperties", "additionalItems"}
_IGNORED |= {"description", "comment", "default"}
_NODE_KEYS = {"type", "properties", "required", "items", "enum", "maxLength", "format"}
_NODE_KEYS |= {"$ref", "definitions", "javaType", "minimum", "maximum", "maxItems"}
_NODE_KEYS |= {"multipleOf", "minItems", "additionalProperties", "additionalItems"}


@dataclass
class FieldIR:
    """One property of a model."""

    wire: str
    attr: str
    required: bool
    kind: str  # str uri datetime int number bool enum object array
    ref: str | None = None  # enum or object class name
    max_length: int | None = None
    one_decimal: bool = False
    item: FieldIR | None = None  # array element (wire/attr unused)
    min_items: int | None = None
    ge: int | None = None
    non_empty: bool = False  # a required string that must not be empty
    type_name: str | None = None  # a type from ocpp_sdk.model replacing StrictStr
    le: int | None = None
    max_items: int | None = None
    doc: str = ""
    alias: str | None = None  # explicit JSON name when ``to_camel(attr)`` differs


@dataclass
class ModelIR:
    """A message or a shared datatype."""

    name: str
    doc: str
    fields: list[FieldIR]
    action: str | None = None  # set for messages
    rules: str | None = None
    extra_allow: bool = False  # additionalProperties is true: keep unknown properties


@dataclass
class EnumIR:
    """An enumeration."""

    name: str
    doc: str
    values: list[str]


@dataclass
class MessageIR:
    """A request/response pair."""

    action: str
    module: str
    doc: str
    request: ModelIR
    response: ModelIR | None  # None for a one-way message (OCPP 2.1 SEND)

    @property
    def models(self) -> list[ModelIR]:
        """The request and, if there is one, the response."""
        return [self.request] if self.response is None else [self.request, self.response]


@dataclass
class SchemaIR:
    """Everything generated for one profile."""

    messages: list[MessageIR] = field(default_factory=list)
    types: dict[str, ModelIR] = field(default_factory=dict)  # in dependency order
    enums: dict[str, EnumIR] = field(default_factory=dict)


class GenError(Exception):
    """The schemas and the profile tables disagree."""


def snake(wire: str) -> str:
    """``idTagInfo`` -> ``id_tag_info``; ``responderURL`` -> ``responder_url``."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", wire).lower()


class _Builder:
    def __init__(self, profile: Profile) -> None:
        self.p = profile
        self.ir = SchemaIR()
        self.type_at = {loc: n for n, t in profile.types.items() for loc in t.locations}
        self.enum_at = {loc: n for n, t in profile.enums.items() for loc in t.locations}
        self.seen_nodes: dict[str, str] = {}  # class name -> canonical schema
        self.used_locations: set[str] = set()
        self.stem = ""
        self.defs: dict[str, Any] = {}
        self.object_names: set[str] = set()

    # -- nodes -------------------------------------------------------------

    def _check_keys(self, node: dict[str, Any], loc: str) -> None:
        for key in node:
            if key not in _NODE_KEYS and key not in _IGNORED:
                raise GenError(f"{loc}: unsupported schema keyword {key!r}")

    def _canonical(self, node: dict[str, Any]) -> str:
        """The node as JSON; ``$ref`` is resolved and ``javaType`` (a Java hint) dropped."""

        def clean(n: Any) -> Any:
            if isinstance(n, dict):
                if "$ref" in n:
                    return clean(self._resolve(n["$ref"])[1])
                return {k: clean(v) for k, v in n.items() if k not in _DOC_KEYS}
            if isinstance(n, list):
                return [clean(x) for x in n]
            return n

        return json.dumps(clean(node), sort_keys=True)

    def _resolve(self, ref: str) -> tuple[str, dict[str, Any]]:
        prefix = "#/definitions/"
        if not ref.startswith(prefix) or ref[len(prefix) :] not in self.defs:
            raise GenError(f"{self.stem}: unresolvable $ref {ref!r}")
        name = ref[len(prefix) :]
        return name, self.defs[name]

    def _remember(self, name: str, node: dict[str, Any], loc: str) -> bool:
        """Record that ``loc`` is class ``name``; ``True`` if it is new."""
        self.used_locations.add(loc)
        canon = self._canonical(node)
        if name in self.seen_nodes:
            if self.seen_nodes[name] != canon:
                raise GenError(f"{loc}: differs from the other places that map to {name}")
            return False
        self.seen_nodes[name] = canon
        return True

    def enum(self, node: dict[str, Any], loc: str, name: str | None = None) -> str:
        name = name or self.enum_at.get(loc)
        if name is None:
            raise GenError(f"{loc}: enum has no name in the profile's enums table")
        if self._remember(name, node, loc):
            doc = self.p.enums[name].doc if name in self.p.enums else _doc(node)
            self.ir.enums[name] = EnumIR(name, doc, list(node["enum"]))
        return name

    def obj(self, node: dict[str, Any], loc: str, name: str | None = None) -> str:
        name = name or self.type_at.get(loc)
        if name is None:
            raise GenError(f"{loc}: object has no name in the profile's types table")
        is_new = self._remember(name, node, loc)
        self._check_keys(node, loc)
        required = set(node.get("required", []))
        fields = [
            self.field(wire, spec, wire in required, f"{loc}.{wire}", name)
            for wire, spec in node.get("properties", {}).items()
        ]
        missing = required - set(node.get("properties", {}))
        if missing:
            raise GenError(f"{loc}: required {sorted(missing)} are not properties")
        if is_new:
            doc = self.p.types[name].doc if name in self.p.types else _doc(node)
            self.ir.types[name] = ModelIR(
                name,
                doc,
                fields,
                rules=self.p.rules.get(name),
                extra_allow=node.get("additionalProperties", True) is True,
            )
        return name

    def field(
        self, wire: str, spec: dict[str, Any], required: bool, loc: str, owner: str
    ) -> FieldIR:
        f = self.value(spec, loc, owner, wire)
        f.wire, f.attr, f.required = wire, snake(wire), required
        if to_camel(f.attr) != wire:
            f.alias = wire  # the generated alias would not give the spec's spelling
        f.doc = f.doc or _doc(spec)
        key = f"{owner}.{wire}"
        if key in self.p.int_min:
            if f.kind not in ("int", "number"):
                raise GenError(f"{key}: int_min on a non-number")
            f.ge = self.p.int_min[key]
        if key in self.p.int_max:
            if f.kind not in ("int", "number"):
                raise GenError(f"{key}: int_max on a non-number")
            f.le = self.p.int_max[key]
        if key in self.p.one_decimal:
            if f.kind != "number":
                raise GenError(f"{key}: one_decimal on a non-number")
            f.one_decimal = True
        if key in self.p.array_min:
            if f.kind != "array":
                raise GenError(f"{key}: array_min on a non-array")
            f.min_items = self.p.array_min[key] or None  # a table entry overrides the schema
        if key in self.p.field_types:
            target = f.item if f.kind == "array" and f.item else f
            if target.kind != "str":
                raise GenError(f"{key}: field_types on a non-string")
            target.type_name = self.p.field_types[key]
        if f.kind == "str" and required and key not in self.p.empty_allowed:
            f.non_empty = True
        return f

    def class_name(self, definition: str, is_enum: bool) -> str:
        """``IdTokenType`` -> ``IdToken``; ``StatusEnumType`` -> ``Status`` (or ``...Enum``)."""
        if not is_enum:
            return definition.removesuffix("Type")
        short = definition.removesuffix("EnumType")
        return f"{short}Enum" if short in self.object_names else short

    def value(self, spec: dict[str, Any], loc: str, owner: str, wire: str) -> FieldIR:
        doc = _doc(spec)
        definition: str | None = None
        if "$ref" in spec:
            definition, spec = self._resolve(spec["$ref"])
            loc = f"{self.stem}#{definition}"
        self._check_keys(spec, loc)
        kind = spec.get("type")
        named = definition is not None and self.p.definitions_naming
        if "enum" in spec:
            name = self.class_name(definition, True) if named and definition else None
            return FieldIR(wire, "", False, "enum", ref=self.enum(spec, loc, name), doc=doc)
        if kind == "object":
            name = self.class_name(definition, False) if named and definition else None
            return FieldIR(wire, "", False, "object", ref=self.obj(spec, loc, name), doc=doc)
        if kind == "array":
            item = self.value(spec["items"], loc + "[]", owner, "")
            return FieldIR(
                wire,
                "",
                False,
                "array",
                item=item,
                min_items=spec.get("minItems"),
                max_items=spec.get("maxItems"),
                doc=doc,
            )
        if kind == "string":
            fmt = spec.get("format")
            if fmt not in (None, "date-time", "uri"):
                raise GenError(f"{loc}: unsupported format {fmt!r}")
            k = {"date-time": "datetime", "uri": "uri"}.get(fmt or "", "str")
            return FieldIR(wire, "", False, k, max_length=spec.get("maxLength"), doc=doc)
        if kind == "integer":
            return FieldIR(
                wire,
                "",
                False,
                "int",
                ge=_bound(spec.get("minimum")),
                le=_bound(spec.get("maximum")),
                doc=doc,
            )
        if kind == "number":
            multiple = spec.get("multipleOf")
            if multiple not in (None, 0.1):
                raise GenError(f"{loc}: unsupported multipleOf {multiple}")
            return FieldIR(
                wire,
                "",
                False,
                "number",
                one_decimal=multiple == 0.1,
                ge=_bound(spec.get("minimum")),
                le=_bound(spec.get("maximum")),
                doc=doc,
            )
        if kind == "boolean":
            return FieldIR(wire, "", False, "bool", doc=doc)
        if kind is None and "properties" not in spec:
            return FieldIR(wire, "", False, "any", doc=doc)  # any JSON value
        raise GenError(f"{loc}: unsupported type {kind!r}")


def _bound(value: Any) -> int | None:
    """A schema ``minimum`` / ``maximum`` (written as a float) as an int."""
    if value is None:
        return None
    if value != int(value):
        raise GenError(f"unsupported fractional bound {value}")
    return int(value)


QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-"})


def _doc(node: dict[str, Any]) -> str:
    """The ``description`` of a schema node as one line of text."""
    text = " ".join(str(node.get("description", "")).split())
    return text.translate(QUOTES)


def load(profile: Profile) -> SchemaIR:
    """Read the schemas of ``profile`` and apply its tables."""
    schema_dir = ROOT / profile.schema_dir
    b = _Builder(profile)
    if profile.definitions_naming:
        b.object_names = {
            d.removesuffix("Type")
            for path in schema_dir.glob("*.json")
            for d, node in json.loads(path.read_text()).get("definitions", {}).items()
            if "enum" not in node
        }
    listed: set[str] = set()
    for module in profile.modules:
        for action in module.messages:
            if action in listed:
                raise GenError(f"{action} is listed twice")
            listed.add(action)
            if action in profile.one_way:  # a SEND: one schema named after the message
                req_node = json.loads((schema_dir / f"{action}.json").read_text())
                b.stem, b.defs = action, req_node.get("definitions", {})
                req_name = b.obj(req_node, action, action)
                req_ir = b.ir.types.pop(req_name)
                req_ir.action = action
                req_ir.doc = profile.descriptions.get(action) or f"The {action} message (a SEND)."
                b.ir.messages.append(MessageIR(action, module.name, req_ir.doc, req_ir, None))
                continue
            rq = f"{action}{profile.request_file_suffix}"
            req_node = json.loads((schema_dir / f"{rq}.json").read_text())
            res_node = json.loads((schema_dir / f"{action}Response.json").read_text())
            for node, stem in ((req_node, rq), (res_node, f"{action}Response")):
                if node.get("type") != "object":
                    raise GenError(f"{stem}: root is not an object")
            b.stem, b.defs = rq, req_node.get("definitions", {})
            request = b.obj(req_node, rq, f"{action}{profile.request_suffix}")
            b.stem, b.defs = f"{action}Response", res_node.get("definitions", {})
            response = b.obj(res_node, f"{action}Response", f"{action}{profile.response_suffix}")
            req_ir, res_ir = b.ir.types.pop(request), b.ir.types.pop(response)
            doc = profile.descriptions.get(action) or f"The {action} message."
            req_ir.action = res_ir.action = action
            req_ir.doc = doc
            res_ir.doc = f"The answer to {action}."
            b.ir.messages.append(MessageIR(action, module.name, doc, req_ir, res_ir))
    if profile.from_station - listed:
        raise GenError(
            f"from_station lists unknown messages: {sorted(profile.from_station - listed)}"
        )
    on_disk = {
        p.stem.removesuffix("Response").removesuffix(profile.request_file_suffix)
        for p in schema_dir.glob("*.json")
    }
    unaccounted = on_disk - listed - profile.deferred
    if unaccounted:
        raise GenError(f"schemas not in any module: {sorted(unaccounted)}")
    stray = (listed | profile.deferred) - on_disk
    if stray:
        raise GenError(f"listed messages without a schema: {sorted(stray)}")
    for table, label in ((profile.types, "types"), (profile.enums, "enums")):
        for name, named in table.items():
            for loc in named.locations:
                if loc not in b.used_locations:
                    raise GenError(f"{label}[{name}]: location {loc} does not exist")
    if profile.definitions_naming and (profile.types or profile.enums):
        raise GenError("definitions_naming and the types/enums tables are exclusive")
    unused_rules = (
        set(profile.rules)
        - set(b.ir.types)
        - {m.request.name for m in b.ir.messages}
        - {m.response.name for m in b.ir.messages if m.response}
    )
    if unused_rules:
        raise GenError(f"rules for unknown models: {sorted(unused_rules)}")
    for m in b.ir.messages:
        m.request.rules = profile.rules.get(m.request.name)
        if m.response:
            m.response.rules = profile.rules.get(m.response.name)
    for limits, label in ((profile.int_min, "int_min"), (profile.array_min, "array_min")):
        known = {
            f"{m.name}.{f.wire}"
            for m in [
                *b.ir.types.values(),
                *(x for ms in b.ir.messages for x in ms.models),
            ]
            for f in m.fields
        }
        for key in limits:
            if key not in known:
                raise GenError(f"{label}: {key} does not exist")
    return b.ir
