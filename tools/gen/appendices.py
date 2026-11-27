"""Renders ``appendices.py`` from the CSV files that come with the specification."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from tools.gen.emit import HEADER, _sorted_all
from tools.gen.profiles import Profile
from tools.gen.schema import QUOTES, ROOT, GenError

_WORDS = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|[.\-_ /]+")


def const_name(value: str) -> str:
    """``AuthCtrlr`` -> ``AUTH_CTRLR``; ``Sample.Clock`` -> ``SAMPLE_CLOCK``."""
    if len(value) <= 4 and value.isalnum():  # units such as dB, kWh, VA stay one word
        return value.upper()
    name = "_".join(w for w in _WORDS.split(value) if w).upper()
    name = re.sub(r"\W", "", name)
    return f"_{name}" if name[:1].isdigit() else name


def read_csv(path: Path) -> list[list[str]]:
    """The rows of a semicolon separated file without its header, cells stripped."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = [[cell.strip() for cell in row] for row in csv.reader(handle, delimiter=";")]
    return rows[1:]


def first_sentence(text: str, limit: int = 88) -> str:
    """One line of a description: its first sentence, cut at a word boundary."""
    text = " ".join(text.split()).translate(QUOTES)
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    sentence = match.group(1) if match else text
    if len(sentence) > limit:
        sentence = sentence[: limit - 3].rsplit(" ", 1)[0] + "..."
    return sentence


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class _Names:
    """Hands out constant names and refuses duplicates."""

    def __init__(self, what: str) -> None:
        self.what, self.used = what, set[str]()

    def get(self, value: str, *, lower_suffix: bool = False) -> str:
        name = const_name(value)
        if name in self.used and lower_suffix:
            name += "_LOWER"
        if name in self.used or not name:
            raise GenError(f"{self.what}: constant name clash for {value!r} ({name})")
        self.used.add(name)
        return name


def _namespace(cls: str, title: str, entries: list[tuple[str, str, str]]) -> list[str]:
    """``class cls`` with one constant per ``(name, value, doc)``."""
    lines = [f"class {cls}:", f'    """{title}"""', ""]
    for name, value, doc in entries:
        lines += [f"    #: {doc}", f"    {name} = {_quote(value)}"]
    return lines


def render(profile: Profile) -> str:
    """The text of ``appendices.py``."""
    assert profile.appendices_dir
    base = ROOT / profile.appendices_dir
    out = [
        HEADER,
        f'"""Standardized components, variables, units, reason codes and security events of OCPP '
        f"{profile.version}.\n\nThe values of the appendices CSV files that come with the "
        'specification. Messages keep\nplain strings; use these constants to avoid typos.\n"""\n',
        "from typing import NamedTuple\n",
    ]
    exported: list[str] = []

    def section(lines: list[str]) -> None:
        out.append("\n".join(lines) + "\n")

    # components
    names, comp = _Names("components"), []
    for row in read_csv(base / "components.csv"):
        if row and row[0]:
            comp.append((names.get(row[0]), row[0], first_sentence(row[1] if len(row) > 1 else "")))
    section(_namespace("Component", "Standardized components (part 2 appendix 3.1).", comp))
    section(["COMPONENTS: tuple[str, ...] = (", *(f"    Component.{n}," for n, _, _ in comp), ")"])
    exported += ["COMPONENTS", "Component"]

    # variables
    names, var, seen = _Names("variables"), [], set[str]()
    infos: list[tuple[str, str, str]] = []
    for row in read_csv(base / "variables.csv"):
        if not row or not row[0] or row[0] in seen:
            continue  # the appendix lists one variable twice
        seen.add(row[0])
        var.append((names.get(row[0]), row[0], first_sentence(row[3] if len(row) > 3 else "")))
        infos.append((var[-1][0], row[1] if len(row) > 1 else "", row[2] if len(row) > 2 else ""))
    section(_namespace("Variable", "Standardized variables (part 2 appendix 3.2).", var))
    section(
        [
            "class VariableInfo(NamedTuple):",
            '    """A standardized variable: name, data type of its values and unit."""',
            "",
            "    name: str",
            "    data_type: str",
            "    unit: str",
        ]
    )
    section(
        [
            "VARIABLES: tuple[VariableInfo, ...] = (",
            *(f"    VariableInfo(Variable.{n}, {_quote(t)}, {_quote(u)})," for n, t, u in infos),
            ")",
        ]
    )
    exported += ["VARIABLES", "Variable", "VariableInfo"]

    # device model
    entries = []
    for row in read_csv(base / "dm_components_vars.csv"):
        if len(row) > 5 and row[0] and row[1]:
            required = row[3].lower() == "yes"
            entries.append((row[0], row[1], row[2], required, row[4], row[5]))
    section(
        [
            'GENERIC = "<generic>"',
            '"""The component of ``DEVICE_MODEL`` entries that apply to every component."""',
        ]
    )
    section(
        [
            "class DeviceModelEntry(NamedTuple):",
            '    """A variable of a standardized component (``required``: must be implemented)."""',
            "",
            "    component: str",
            "    variable: str",
            "    instance: str",
            "    required: bool",
            "    data_type: str",
            "    unit: str",
        ]
    )
    section(
        [
            "DEVICE_MODEL: tuple[DeviceModelEntry, ...] = (",
            *(
                "    DeviceModelEntry("
                f"{_quote(c)}, {_quote(v)}, {_quote(i)}, {r}, {_quote(t)}, {_quote(u)}),"
                for c, v, i, r, t, u in entries
            ),
            ")",
        ]
    )
    exported += ["DEVICE_MODEL", "GENERIC", "DeviceModelEntry"]

    # units
    names, units = _Names("units"), []
    for row in read_csv(base / "units_of_measure.csv"):
        if row and row[0]:
            units.append(
                (
                    names.get(row[0], lower_suffix=True),
                    row[0],
                    first_sentence(row[1] if len(row) > 1 else ""),
                )
            )
    section(_namespace("Unit", "Standardized units of measure (part 2 appendix 3.4).", units))
    section(["UNITS: tuple[str, ...] = (", *(f"    Unit.{n}," for n, _, _ in units), ")"])
    exported += ["UNITS", "Unit"]

    # reason codes
    names, codes, table, group = _Names("reason codes"), [], [], ""
    for row in read_csv(base / "reason_codes.csv"):
        code = row[1] if len(row) > 1 else ""
        if not code:
            if row and row[0]:
                group = row[0]  # a row that only names the group of the codes below it
            continue
        name = names.get(code)
        codes.append(
            (name, code, f"({group}) {first_sentence(row[2] if len(row) > 2 else '', 70)}")
        )
        table.append((name, group, row[3] if len(row) > 3 else ""))
    section(
        _namespace(
            "ReasonCode", "Reason codes for ``StatusInfo.reason_code`` (part 2 appendix 5).", codes
        )
    )
    section(
        [
            "class ReasonCodeInfo(NamedTuple):",
            '    """A standardized reason code: its group and the messages it is used for."""',
            "",
            "    code: str",
            "    group: str",
            "    used_for: str",
        ]
    )
    section(
        [
            "REASON_CODES: tuple[ReasonCodeInfo, ...] = (",
            *(
                f"    ReasonCodeInfo(ReasonCode.{n}, {_quote(g)}, {_quote(u)}),"
                for n, g, u in table
            ),
            ")",
        ]
    )
    exported += ["REASON_CODES", "ReasonCode", "ReasonCodeInfo"]

    # security events
    names, events, critical = _Names("security events"), [], []
    for row in read_csv(base / "security_events.csv"):
        if row and row[0]:
            name = names.get(row[0])
            events.append((name, row[0], first_sentence(row[1] if len(row) > 1 else "")))
            if len(row) > 2 and row[2].lower() == "yes":
                critical.append(name)
    section(
        _namespace("SecurityEvent", "Standardized security events (part 2 appendix 1).", events)
    )
    section(
        [
            "SECURITY_EVENTS: tuple[str, ...] = (",
            *(f"    SecurityEvent.{n}," for n, _, _ in events),
            ")",
            "",
            "CRITICAL_SECURITY_EVENTS: frozenset[str] = frozenset(",
            "    {",
            *(f"        SecurityEvent.{n}," for n in critical),
            "    }",
            ")",
            '"""The events marked critical: to be stored and reported even after being offline."""',
        ]
    )
    section(
        [
            "def is_known_security_event(name: str) -> bool:",
            '    """Whether ``name`` is a standardized security event.',
            "",
            "    Example:",
            '        >>> is_known_security_event("StartupOfTheDevice")',
            "        True",
            '        >>> is_known_security_event("Other")',
            "        False",
            '    """',
            "    return name in SECURITY_EVENTS",
            "",
            "",
            "def is_critical_security_event(name: str) -> bool:",
            '    """Whether ``name`` is a standardized security event marked critical.',
            "",
            "    Example:",
            '        >>> is_critical_security_event("StartupOfTheDevice")',
            "        True",
            '    """',
            "    return name in CRITICAL_SECURITY_EVENTS",
        ]
    )
    exported += [
        "CRITICAL_SECURITY_EVENTS",
        "SECURITY_EVENTS",
        "SecurityEvent",
        "is_critical_security_event",
        "is_known_security_event",
    ]
    # value lists kept in their own CSV files (2.1)
    for extra in profile.extra_sets:
        names, values = _Names(extra.title), []
        for row in read_csv(base / extra.file):
            if row and row[0]:
                text = row[1] if len(row) == 2 else ", ".join(c for c in row[1:] if c)
                values.append((names.get(row[0]), row[0], first_sentence(text)))
        section(_namespace(extra.cls, f"Standardized {extra.title} (appendices CSV).", values))
        section(
            [
                f"{extra.tuple_name}: tuple[str, ...] = (",
                *(f"    {extra.cls}.{n}," for n, _, _ in values),
                ")",
            ]
        )
        exported += [extra.tuple_name, extra.cls]
    out.insert(3, f"__all__ = {_sorted_all(exported)}\n")
    return "\n\n".join(out)
