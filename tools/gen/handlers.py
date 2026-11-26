"""Renders the handler protocols, ``Unimplemented...`` bases, dispatch tables and typed calls."""

from __future__ import annotations

import re
import textwrap

from tools.gen.emit import HEADER, _sorted_all
from tools.gen.profiles import Module, Profile
from tools.gen.schema import MessageIR, SchemaIR

SIDES = ("charge_point", "csms")


def snake(action: str) -> str:
    """``BootNotification`` -> ``boot_notification``."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", action).lower()


_TITLE = {"charge_point": "Charge Point", "csms": "Central System"}


def split(profile: Profile, ir: SchemaIR, side: str) -> tuple[list[MessageIR], list[MessageIR]]:
    """``(received, sent)`` by ``side``; DataTransfer is both."""
    station = side == "charge_point"
    received, sent = [], []
    for m in ir.messages:
        from_station = m.action in profile.from_station
        both = m.action == "DataTransfer"
        if both or from_station != station:
            received.append(m)
        if both or from_station == station:
            sent.append(m)
    return received, sent


def _signature(side: str, m: MessageIR) -> str:
    result = f"{m.response.name} | Awaitable[{m.response.name}]"
    if side == "csms":
        return f"(self, charge_point: ChargePoint, request: {m.request.name}) -> {result}"
    return f"(self, request: {m.request.name}) -> {result}"


def _protocol(side: str, module: Module, messages: list[MessageIR]) -> str:
    name = f"{module.handler}Handler"
    sender = "Central System" if side == "csms" else "Charge Point"
    other = "Charge Point" if side == "csms" else "Central System"
    lines = [
        f"class {name}(Protocol):",
        f'    """Handles the {module.title} messages that the {sender}',
        f"    receives from the {other}.",
        "",
        "    Methods may be sync or async. Raise ``ocpp_sdk.errors.CallError`` to answer with a",
        "    specific CALLERROR; any other exception is answered with ``InternalError``.",
        "",
        "    Example:",
        f"        >>> {name} in Unimplemented{name}.__mro__",
        "        True",
        '    """',
    ]
    for m in messages:
        lines += [
            "",
            f"    def on_{snake(m.action)}{_signature(side, m)}:",
            f'        """{m.doc}"""',
            "        ...",
        ]
    return "\n".join(lines)


def _unimplemented(side: str, module: Module, messages: list[MessageIR]) -> str:
    base = f"{module.handler}Handler"
    name = f"Unimplemented{base}"
    lines = [
        f"class {name}({base}):",
        f'    """Answers every {module.title} message with ``NotSupported``.',
        "",
        "    Override the messages you support.",
        "",
        "    Example:",
        f"        >>> class MyHandler({name}):",
        "        ...     pass",
        "        >>> " + base + " in MyHandler.__mro__",
        "        True",
        '    """',
    ]
    for m in messages:
        lines += [
            "",
            f"    def on_{snake(m.action)}{_signature(side, m)}:",
            '        """Answers ``NotSupported``."""',
            f'        raise CallError(ErrorCodeV16.NOT_SUPPORTED, "{m.action} is not supported")',
        ]
    return "\n".join(lines)


def _call(m: MessageIR, *, by_id: bool) -> str:
    who = "charge_point_id: str, " if by_id else ""
    target = "charge_point_id, " if by_id else ""
    helper = "_call_charge_point" if by_id else "_call"
    id_doc = (
        "            charge_point_id: The station to call; it must be connected.\n" if by_id else ""
    )
    caller = (
        "csms." + snake(m.action) + "('CP-1', request)"
        if by_id
        else "peer." + snake(m.action) + "(request)"
    )
    summary = textwrap.fill(
        f"Sends {m.action}: {m.doc[0].lower() + m.doc[1:]}",
        width=88,
        subsequent_indent="        ",
    )
    return f'''
    async def {snake(m.action)}(
        self, {who}request: {m.request.name}, *, timeout: float | None = None
    ) -> {m.response.name}:
        """{summary}

        Args:
{id_doc}            request: The request to send.
            timeout: Seconds to wait for the answer; the endpoint's default if ``None``.

        Returns:
            The answer of the peer.

        Raises:
            NotConnectedError: There is no connection (nothing is queued or retried).
            CallTimeoutError: No answer arrived in time.
            CallError: The peer answered with a CALLERROR.
            ValidationError: The request or the answer is invalid.

        Example:
            >>> await {caller}  # doctest: +SKIP
        """
        return cast({m.response.name}, await self.{helper}({target}request, timeout))
'''


def _calls(name: str, doc: str, sent: list[MessageIR], *, by_id: bool) -> str:
    helper = (
        "    async def _call_charge_point(\n"
        "        self, charge_point_id: str, request: BaseModel, timeout: float | None\n"
        "    ) -> BaseModel:\n"
        '        """Send ``request`` to station ``charge_point_id`` (the class provides it)."""\n'
        "        raise NotImplementedError\n"
        if by_id
        else "    async def _call(self, request: BaseModel, timeout: float | None) -> BaseModel:\n"
        '        """Send ``request`` and wait for the answer (provided by the class)."""\n'
        "        raise NotImplementedError\n"
    )
    body = "".join(_call(m, by_id=by_id) for m in sent)
    return f'class {name}:\n    """{doc}"""\n\n{helper}{body}'


def render(profile: Profile, ir: SchemaIR, side: str) -> str:
    """The generated handlers module of one side."""
    received, sent = split(profile, ir, side)
    parts: list[str] = []
    dispatch: list[str] = []
    names: list[str] = []
    for module in profile.modules:
        got = [m for m in received if m.module == module.name]
        if not got:
            continue
        parts += [_protocol(side, module, got), _unimplemented(side, module, got)]
        names += [f"{module.handler}Handler", f"Unimplemented{module.handler}Handler"]
        dispatch += [
            f'    "{m.action}": ("{module.config_field}", "on_{snake(m.action)}"),' for m in got
        ]
    table = "DISPATCH: dict[str, tuple[str, str]] = {\n" + "\n".join(dispatch) + "\n}"
    table += '\n"""Action -> (Config field, handler method) for the messages this side receives."""'
    names.append("DISPATCH")
    if side == "charge_point":
        parts.append(
            _calls(
                "ChargePointCalls",
                "Typed methods for the messages a Charge Point sends.",
                sent,
                by_id=False,
            )
        )
        names.append("ChargePointCalls")
    else:
        parts.append(
            _calls(
                "StationCalls",
                "Typed methods for the messages the CSMS sends to one station.",
                sent,
                by_id=False,
            )
        )
        parts.append(
            _calls(
                "CSMSCalls",
                "Typed methods for the messages the CSMS sends, by station ID.",
                sent,
                by_id=True,
            )
        )
        names += ["StationCalls", "CSMSCalls"]
    pkg = f"ocpp_sdk.{profile.package}"
    mods = "\n".join(
        f"from {pkg}.{mod.name} import "
        + ", ".join(
            sorted(
                c.name for m in ir.messages if m.module == mod.name for c in (m.request, m.response)
            )
        )
        for mod in profile.modules
    )
    checking = (
        ["\nif TYPE_CHECKING:", "    from ocpp_sdk.v16.csms import ChargePoint\n"]
        if side == "csms"
        else [""]
    )
    head = [
        HEADER,
        f'"""Handler protocols, dispatch table and typed calls of the OCPP {profile.version} '
        f'{_TITLE[side]} side."""\n',
        "from __future__ import annotations\n",
        "from collections.abc import Awaitable",
        "from typing import TYPE_CHECKING, Protocol, cast\n",
        "from pydantic import BaseModel\n",
        "from ocpp_sdk.errors import CallError, ErrorCodeV16",
        mods,
        *checking,
        f"__all__ = {_sorted_all(names)}\n",
    ]
    return "\n".join(head) + "\n\n" + "\n\n\n".join([*parts, table]) + "\n"
