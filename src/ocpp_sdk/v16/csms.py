"""OCPP 1.6 Central System (CSMS): accepts Charge Points and exchanges messages.

Example:
    >>> from ocpp_sdk.v16.csms import CSMS, Config
    >>> csms = CSMS(Config(), port=0)
    >>> csms.charge_point_ids()
    []
"""

from __future__ import annotations

import inspect
import logging
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import TracebackType

from pydantic import BaseModel

from ocpp_sdk._internal.dispatch import make_handler
from ocpp_sdk.errors import NotConnectedError
from ocpp_sdk.ocppj.endpoint import DEFAULT_QUEUE_SIZE, DEFAULT_RESPONSE_TIMEOUT, Endpoint
from ocpp_sdk.transport.connection import Connection, FrameSink
from ocpp_sdk.transport.server import Server
from ocpp_sdk.v16 import new_registry
from ocpp_sdk.v16.csms_handlers import (
    DISPATCH,
    CoreHandler,
    CSMSCalls,
    FirmwareHandler,
    SecurityHandler,
    StationCalls,
)
from ocpp_sdk.versions import Version

__all__ = ["CSMS", "ChargePoint", "Config"]

logger = logging.getLogger("ocpp_sdk.v16.csms")

_MaybeAwaitable = Awaitable[object] | object


@dataclass
class Config:
    """The handlers of the messages a Central System receives, one per feature profile.

    A profile left as ``None`` is answered ``NotSupported``. Core, Firmware Management and Security
    have messages a Central System receives. Handlers get the :class:`ChargePoint` session first.

    Example:
        >>> from ocpp_sdk.v16.csms import Config
        >>> Config().core is None
        True
    """

    core: CoreHandler | None = None
    firmware: FirmwareHandler | None = None
    security: SecurityHandler | None = None


class ChargePoint(StationCalls):
    """A connected Charge Point, as the Central System sees it.

    A session belongs to one connection: after the station reconnects, the handlers get a new
    session object and the old one raises ``NotConnectedError``.

    Example:
        >>> async def on_connect(station: ChargePoint) -> None:  # doctest: +SKIP
        ...     print(station.charge_point_id)
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._endpoint: Endpoint | None = None

    @property
    def charge_point_id(self) -> str:
        """The station's ID, from the URL path."""
        return self._connection.charge_point_id

    @property
    def connection(self) -> Connection:
        """The transport connection (address, TLS certificate, ...)."""
        return self._connection

    @property
    def connected(self) -> bool:
        """Whether this session's connection is still up."""
        return self._endpoint is not None and not self._endpoint.closed

    async def _call(
        self,
        request: BaseModel,
        timeout: float | None,  # noqa: ASYNC109
    ) -> BaseModel:
        endpoint = self._endpoint
        if endpoint is None or endpoint.closed:
            raise NotConnectedError(f"{self.charge_point_id} is not connected")
        return await endpoint.call(request, timeout=timeout)


class CSMS(CSMSCalls):
    """An OCPP 1.6 Central System (the server side).

    Args:
        config: Handlers for the messages the stations send.
        host, port: Where to listen (``port=0`` picks a free one; see :attr:`port`).
        ssl_context: Enables TLS (security profiles 2 and 3).
        known_id: ``known_id(charge_point_id)``; false answers HTTP 404.
        authenticate: ``authenticate(charge_point_id, password)``; enables HTTP Basic auth.
        check_certificate_identity, operator_name: Security profile 3 checks.
        on_connect, on_disconnect: Called with the :class:`ChargePoint` session when a station
            connects / its connection ended (sync or async).
        response_timeout: Default seconds to wait for an answer to a call.
        queue_size: How many calls may wait behind the outstanding one.
        ping_interval, ping_timeout, max_message_size, open_timeout, close_timeout:
            Passed to the transport :class:`~ocpp_sdk.transport.server.Server`.

    Example:
        >>> async def main() -> None:  # doctest: +SKIP
        ...     async with CSMS(Config(core=MyCoreHandler())) as csms:
        ...         await csms.reset("CP-1", ResetRequest(type=ResetType.SOFT))
    """

    def __init__(
        self,
        config: Config | None = None,
        *,
        host: str = "127.0.0.1",
        port: int = 9000,
        ssl_context: ssl.SSLContext | None = None,
        known_id: Callable[[str], _MaybeAwaitable] | None = None,
        authenticate: Callable[[str, str], _MaybeAwaitable] | None = None,
        check_certificate_identity: bool = False,
        operator_name: str | None = None,
        on_connect: Callable[[ChargePoint], _MaybeAwaitable] | None = None,
        on_disconnect: Callable[[ChargePoint], _MaybeAwaitable] | None = None,
        response_timeout: float = DEFAULT_RESPONSE_TIMEOUT,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        ping_interval: float | None = 30.0,
        ping_timeout: float | None = 10.0,
        max_message_size: int = 1024 * 1024,
        open_timeout: float = 10.0,
        close_timeout: float = 5.0,
    ) -> None:
        self._config = config or Config()
        self._registry = new_registry()
        self._response_timeout = response_timeout
        self._queue_size = queue_size
        self._on_connect_hook = on_connect
        self._on_disconnect_hook = on_disconnect
        self._sessions: dict[str, ChargePoint] = {}
        self._server = Server(
            self._on_connect,
            on_disconnect=self._on_disconnect,
            host=host,
            port=port,
            versions=(Version.OCPP16,),
            ssl_context=ssl_context,
            known_id=known_id,
            authenticate=authenticate,
            check_certificate_identity=check_certificate_identity,
            operator_name=operator_name,
            ping_interval=ping_interval,
            ping_timeout=ping_timeout,
            max_message_size=max_message_size,
            open_timeout=open_timeout,
            close_timeout=close_timeout,
        )

    async def start(self) -> None:
        """Start listening."""
        await self._server.start()

    @property
    def port(self) -> int:
        """The port actually listening."""
        return self._server.port

    def charge_point_ids(self) -> list[str]:
        """The IDs of the connected stations, in identity order."""
        return sorted(self._sessions)

    def charge_point(self, charge_point_id: str) -> ChargePoint | None:
        """The session of a connected station, or ``None``."""
        return self._sessions.get(charge_point_id)

    async def for_each(self, fn: Callable[[ChargePoint], _MaybeAwaitable]) -> None:
        """Call ``fn(session)`` for every connected station, in identity order (sync or async)."""
        for charge_point_id in self.charge_point_ids():
            session = self._sessions.get(charge_point_id)
            if session is not None:
                await _resolve(fn(session))

    async def shutdown(
        self,
        timeout: float = 10.0,  # noqa: ASYNC109 - public API takes a timeout
    ) -> None:
        """Stop accepting, close every connection with 1001 and wait up to ``timeout`` s."""
        await self._server.shutdown(timeout)

    async def __aenter__(self) -> CSMS:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.shutdown()

    async def _on_connect(self, connection: Connection) -> FrameSink:
        session = ChargePoint(connection)
        endpoint = Endpoint(
            self._registry,
            connection.send,
            handler=make_handler(self._config, DISPATCH, session),
            response_timeout=self._response_timeout,
            queue_size=self._queue_size,
        )
        session._endpoint = endpoint
        self._sessions[connection.charge_point_id] = session
        if self._on_connect_hook is not None:
            await _resolve(self._on_connect_hook(session))
        return endpoint

    async def _on_disconnect(self, connection: Connection) -> None:
        session = self._sessions.get(connection.charge_point_id)
        if session is None or session.connection is not connection:
            return  # a newer connection of the same station replaced this one
        del self._sessions[connection.charge_point_id]
        if self._on_disconnect_hook is not None:
            await _resolve(self._on_disconnect_hook(session))

    async def _call_charge_point(
        self,
        charge_point_id: str,
        request: BaseModel,
        timeout: float | None,  # noqa: ASYNC109
    ) -> BaseModel:
        session = self._sessions.get(charge_point_id)
        if session is None:
            raise NotConnectedError(f"{charge_point_id} is not connected")
        return await session._call(request, timeout)


async def _resolve(value: object) -> None:
    if inspect.isawaitable(value):
        await value
