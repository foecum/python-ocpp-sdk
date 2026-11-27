"""Connection lifecycle shared by the high-level station and CSMS classes of every version.

The public classes (``v16.ChargePoint``, ``v201.ChargingStation``, the CSMS classes and their
session objects) hold one of these and forward to it, so no internal type is exposed.
"""

from __future__ import annotations

import asyncio
import inspect
import ssl
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from ocpp_sdk._internal.dispatch import make_handler
from ocpp_sdk.errors import NotConnectedError
from ocpp_sdk.ocppj.endpoint import Endpoint
from ocpp_sdk.ocppj.registry import Registry
from ocpp_sdk.transport.client import Client, Reconnect
from ocpp_sdk.transport.connection import Connection, FrameSink
from ocpp_sdk.transport.server import Server
from ocpp_sdk.versions import Version

__all__ = ["CSMSCore", "SessionCore", "StationCore"]

Dispatch = Mapping[str, tuple[str, str]]
_MaybeAwaitable = Awaitable[object] | object
S = TypeVar("S")


def _drop_action(
    handler: Callable[..., _MaybeAwaitable] | None, *leading: Any
) -> Callable[[str, BaseModel], Awaitable[None]] | None:
    """Adapt ``handler(*leading, message)`` to the endpoint's ``(action, message)`` SEND handler."""
    if handler is None:
        return None

    async def run(action: str, message: BaseModel) -> None:
        await resolve(handler(*leading, message))

    return run


async def resolve(value: object) -> None:
    """Await ``value`` if it is awaitable (hooks may be sync or async)."""
    if inspect.isawaitable(value):
        await value


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


class StationCore:
    """The client side: one reconnecting connection to a CSMS."""

    def __init__(
        self,
        url: str,
        *,
        version: Version,
        registry: Registry,
        config: object,
        dispatch: Dispatch,
        response_timeout: float,
        queue_size: int,
        password: str | None,
        ssl_context: ssl.SSLContext | None,
        reconnect: Reconnect | None,
        ping_interval: float | None,
        ping_timeout: float | None,
        max_message_size: int,
        open_timeout: float,
        close_timeout: float,
        send_handler: Callable[[BaseModel], _MaybeAwaitable] | None = None,
    ) -> None:
        self._registry = registry
        self._config = config
        self._dispatch = dispatch
        self._response_timeout = response_timeout
        self._queue_size = queue_size
        self._send_handler = send_handler
        self._endpoint: Endpoint | None = None
        self._online = asyncio.Event()
        self._client = Client(
            url,
            self._on_connect,
            versions=(version,),
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
        return self._endpoint is not None and not self._endpoint.closed

    @property
    def connection(self) -> Connection | None:
        return self._client.connection

    async def wait_online(self) -> None:
        await self._online.wait()

    def start(self) -> None:
        self._client.start()

    async def wait_connected(self, timeout: float | None) -> Connection:  # noqa: ASYNC109
        return await self._client.wait_connected(timeout)

    async def enter(self) -> None:
        await self._client.__aenter__()

    async def close(self) -> None:
        await self._client.close()

    async def _on_connect(self, connection: Connection) -> FrameSink:
        endpoint = Endpoint(
            self._registry,
            connection.send,
            handler=make_handler(self._config, self._dispatch),
            response_timeout=self._response_timeout,
            queue_size=self._queue_size,
            send_handler=_drop_action(self._send_handler),
        )
        self._endpoint = endpoint
        self._online.set()
        return _OnlineSink(endpoint, self._online)

    async def call(
        self,
        request: BaseModel,
        timeout: float | None,  # noqa: ASYNC109
    ) -> BaseModel:
        endpoint = self._endpoint
        if endpoint is None or endpoint.closed:
            raise NotConnectedError("not connected to the Central System")
        return await endpoint.call(request, timeout=timeout)

    async def send(self, message: BaseModel) -> None:
        endpoint = self._endpoint
        if endpoint is None or endpoint.closed:
            raise NotConnectedError("not connected to the Central System")
        await endpoint.send(message)


class SessionCore:
    """One connected station, as seen by the CSMS."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.endpoint: Endpoint | None = None

    @property
    def charge_point_id(self) -> str:
        return self.connection.charge_point_id

    @property
    def connected(self) -> bool:
        return self.endpoint is not None and not self.endpoint.closed

    async def call(
        self,
        request: BaseModel,
        timeout: float | None,  # noqa: ASYNC109
    ) -> BaseModel:
        endpoint = self.endpoint
        if endpoint is None or endpoint.closed:
            raise NotConnectedError(f"{self.charge_point_id} is not connected")
        return await endpoint.call(request, timeout=timeout)

    async def send(self, message: BaseModel) -> None:
        endpoint = self.endpoint
        if endpoint is None or endpoint.closed:
            raise NotConnectedError(f"{self.charge_point_id} is not connected")
        await endpoint.send(message)


class CSMSCore(Generic[S]):
    """The server side: accepts stations and keeps one session object per connection.

    ``wrap`` turns a :class:`SessionCore` into the version's public session object, which is
    what handlers and hooks receive.
    """

    def __init__(
        self,
        *,
        version: Version,
        registry: Registry,
        config: object,
        dispatch: Dispatch,
        wrap: Callable[[SessionCore], S],
        on_connect: Callable[[S], _MaybeAwaitable] | None,
        on_disconnect: Callable[[S], _MaybeAwaitable] | None,
        response_timeout: float,
        queue_size: int,
        host: str,
        port: int,
        ssl_context: ssl.SSLContext | None,
        known_id: Callable[[str], _MaybeAwaitable] | None,
        authenticate: Callable[[str, str], _MaybeAwaitable] | None,
        check_certificate_identity: bool,
        operator_name: str | None,
        ping_interval: float | None,
        ping_timeout: float | None,
        max_message_size: int,
        open_timeout: float,
        close_timeout: float,
        send_handler: Callable[[S, BaseModel], _MaybeAwaitable] | None = None,
    ) -> None:
        self._registry = registry
        self._config = config
        self._dispatch = dispatch
        self._send_handler = send_handler
        self._wrap = wrap
        self._on_connect_hook = on_connect
        self._on_disconnect_hook = on_disconnect
        self._response_timeout = response_timeout
        self._queue_size = queue_size
        self._sessions: dict[str, tuple[S, SessionCore]] = {}
        self._live: dict[Connection, S] = {}  # every connection whose on_connect hook ran
        self._server = Server(
            self._on_connect,
            on_disconnect=self._on_disconnect,
            host=host,
            port=port,
            versions=(version,),
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
        await self._server.start()

    @property
    def port(self) -> int:
        return self._server.port

    def ids(self) -> list[str]:
        return sorted(self._sessions)

    def session(self, charge_point_id: str) -> S | None:
        entry = self._sessions.get(charge_point_id)
        return entry[0] if entry else None

    async def for_each(self, fn: Callable[[S], _MaybeAwaitable]) -> None:
        for charge_point_id in self.ids():
            entry = self._sessions.get(charge_point_id)
            if entry is not None:
                await resolve(fn(entry[0]))

    async def shutdown(self, timeout: float) -> None:  # noqa: ASYNC109
        await self._server.shutdown(timeout)

    async def call(
        self,
        charge_point_id: str,
        request: BaseModel,
        timeout: float | None,  # noqa: ASYNC109
    ) -> BaseModel:
        entry = self._sessions.get(charge_point_id)
        if entry is None:
            raise NotConnectedError(f"{charge_point_id} is not connected")
        return await entry[1].call(request, timeout)

    async def _on_connect(self, connection: Connection) -> FrameSink:
        core = SessionCore(connection)
        session = self._wrap(core)
        endpoint = Endpoint(
            self._registry,
            connection.send,
            handler=make_handler(self._config, self._dispatch, session),
            response_timeout=self._response_timeout,
            queue_size=self._queue_size,
            send_handler=_drop_action(self._send_handler, session),
        )
        core.endpoint = endpoint
        self._sessions[connection.charge_point_id] = (session, core)
        self._live[connection] = session
        if self._on_connect_hook is not None:
            try:
                await resolve(self._on_connect_hook(session))
            except BaseException:
                # The server never gets the sink, so close it here; no on_disconnect follows.
                del self._live[connection]
                self._forget(connection)
                await endpoint.close()
                raise
        return endpoint

    async def _on_disconnect(self, connection: Connection) -> None:
        session = self._live.pop(connection, None)
        self._forget(connection)  # unless a newer connection of the same station replaced it
        if session is not None and self._on_disconnect_hook is not None:
            await resolve(self._on_disconnect_hook(session))

    def _forget(self, connection: Connection) -> None:
        entry: Any = self._sessions.get(connection.charge_point_id)
        if entry is not None and entry[1].connection is connection:
            del self._sessions[connection.charge_point_id]
