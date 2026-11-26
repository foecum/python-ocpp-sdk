"""OCPP 1.6 Charge Point: connects to a Central System and exchanges messages.

Example:
    >>> from ocpp_sdk.v16.charge_point import ChargePoint, Config
    >>> cp = ChargePoint("ws://localhost:9000/ocpp/CP-1", Config())
    >>> cp.connected
    False
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from dataclasses import dataclass
from types import TracebackType

from pydantic import BaseModel

from ocpp_sdk._internal.dispatch import make_handler
from ocpp_sdk.errors import NotConnectedError
from ocpp_sdk.ocppj.endpoint import DEFAULT_QUEUE_SIZE, DEFAULT_RESPONSE_TIMEOUT, Endpoint
from ocpp_sdk.transport.client import Client, Reconnect
from ocpp_sdk.transport.connection import Connection, FrameSink
from ocpp_sdk.v16 import new_registry
from ocpp_sdk.v16.charge_point_handlers import (
    DISPATCH,
    ChargePointCalls,
    CoreHandler,
    FirmwareHandler,
    LocalAuthListHandler,
    RemoteTriggerHandler,
    ReservationHandler,
    SecurityHandler,
    SmartChargingHandler,
)
from ocpp_sdk.versions import Version

__all__ = ["ChargePoint", "Config"]

logger = logging.getLogger("ocpp_sdk.v16.charge_point")

_RECONNECT = Reconnect()


@dataclass
class Config:
    """The handlers of the messages a Charge Point receives, one per feature profile.

    A profile left as ``None`` is answered ``NotSupported``. Subclass the matching
    ``Unimplemented<Profile>Handler`` to implement only some of a profile's messages.

    Example:
        >>> from ocpp_sdk.v16.charge_point import Config
        >>> from ocpp_sdk.v16.charge_point_handlers import UnimplementedCoreHandler
        >>> Config(core=UnimplementedCoreHandler()).firmware is None
        True
    """

    core: CoreHandler | None = None
    firmware: FirmwareHandler | None = None
    local_auth_list: LocalAuthListHandler | None = None
    reservation: ReservationHandler | None = None
    smart_charging: SmartChargingHandler | None = None
    remote_trigger: RemoteTriggerHandler | None = None
    security: SecurityHandler | None = None


class _OnlineSink:
    """Wraps the endpoint to clear the online flag when its connection ends."""

    def __init__(self, endpoint: Endpoint, online: asyncio.Event) -> None:
        self._endpoint = endpoint
        self._online = online

    def feed(self, raw: str) -> None:
        self._endpoint.feed(raw)

    async def close(self) -> None:
        self._online.clear()
        await self._endpoint.close()


class ChargePoint(ChargePointCalls):
    """An OCPP 1.6 Charge Point (the client side).

    Args:
        url: ``ws://`` or ``wss://`` URL of the Central System ending in the charge point ID.
        config: Handlers for the messages the Central System sends.
        password: HTTP Basic password (security profiles 1 and 2).
        ssl_context: TLS context for ``wss://`` (profiles 2 and 3).
        reconnect: Back-off after a lost connection (OCPP-J 5.4); ``None`` disables it.
        response_timeout: Default seconds to wait for an answer to a call.
        queue_size: How many calls may wait behind the outstanding one.
        ping_interval, ping_timeout, max_message_size, open_timeout, close_timeout:
            Passed to the transport :class:`~ocpp_sdk.transport.client.Client`.

    Offline, calls fail fast with ``NotConnectedError``; nothing is queued or retried, and the
    station never sends BootNotification or Heartbeat on its own.

    Example:
        >>> async def main() -> None:  # doctest: +SKIP
        ...     async with ChargePoint("ws://localhost:9000/ocpp/CP-1") as cp:
        ...         await cp.heartbeat(HeartbeatRequest())
    """

    def __init__(
        self,
        url: str,
        config: Config | None = None,
        *,
        password: str | None = None,
        ssl_context: ssl.SSLContext | None = None,
        reconnect: Reconnect | None = _RECONNECT,
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
        self._endpoint: Endpoint | None = None
        self._online = asyncio.Event()
        self._client = Client(
            url,
            self._on_connect,
            versions=(Version.OCPP16,),
            password=password,
            ssl_context=ssl_context,
            reconnect=reconnect,
            ping_interval=ping_interval,
            ping_timeout=ping_timeout,
            max_message_size=max_message_size,
            open_timeout=open_timeout,
            close_timeout=close_timeout,
        )

    @property
    def connected(self) -> bool:
        """Whether a connection to the Central System is up."""
        return self._endpoint is not None and not self._endpoint.closed

    @property
    def connection(self) -> Connection | None:
        """The live transport connection, or ``None`` while offline."""
        return self._client.connection

    async def wait_online(self) -> None:
        """Wait until a connection is up (returns at once if it already is).

        Unlike :meth:`wait_connected` this also works after a connection was lost and is
        restored by reconnecting.
        """
        await self._online.wait()

    def start(self) -> None:
        """Start connecting in the background (idempotent)."""
        self._client.start()

    async def wait_connected(
        self,
        timeout: float | None = None,  # noqa: ASYNC109 - public API takes a timeout
    ) -> Connection:
        """Wait until connected; see :meth:`~ocpp_sdk.transport.client.Client.wait_connected`."""
        return await self._client.wait_connected(timeout)

    async def close(self) -> None:
        """Close the connection and stop reconnecting."""
        await self._client.close()

    async def __aenter__(self) -> ChargePoint:
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def _on_connect(self, connection: Connection) -> FrameSink:
        endpoint = Endpoint(
            self._registry,
            connection.send,
            handler=make_handler(self._config, DISPATCH),
            response_timeout=self._response_timeout,
            queue_size=self._queue_size,
        )
        self._endpoint = endpoint
        self._online.set()
        return _OnlineSink(endpoint, self._online)

    async def _call(
        self,
        request: BaseModel,
        timeout: float | None,  # noqa: ASYNC109
    ) -> BaseModel:
        endpoint = self._endpoint
        if endpoint is None or endpoint.closed:
            raise NotConnectedError("not connected to the Central System")
        return await endpoint.call(request, timeout=timeout)
