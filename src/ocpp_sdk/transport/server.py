"""WebSocket server for Central Systems (CSMS).

Example:
    >>> from ocpp_sdk.transport.server import Server
    >>> server = Server(on_connect=None)  # doctest: +SKIP
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import ssl
from collections.abc import Awaitable, Callable, Sequence
from http import HTTPStatus
from types import TracebackType
from typing import Any

from websockets.asyncio.server import Server as WsServer
from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response
from websockets.typing import Subprotocol

from ocpp_sdk.transport.auth import (
    certificate_identity_ok,
    charge_point_id_from_path,
    parse_basic_auth,
)
from ocpp_sdk.transport.connection import Connection, FrameSink
from ocpp_sdk.versions import Version

__all__ = ["OnConnect", "OnDisconnect", "Server"]

logger = logging.getLogger("ocpp_sdk.transport.server")

OnConnect = Callable[[Connection], Awaitable[FrameSink]]
OnDisconnect = Callable[[Connection], Awaitable[None]]
_MaybeAwaitable = Any


async def _resolve(value: _MaybeAwaitable) -> Any:
    return await value if inspect.isawaitable(value) else value


class Server:
    """Accepts charge point connections and hands their frames to a sink.

    Args:
        on_connect: Called once per accepted connection; returns the
            :class:`~ocpp_sdk.transport.connection.FrameSink` (usually an
            ``Endpoint``) that receives its frames.
        on_disconnect: Called after the connection ended and its sink closed.
        host, port: Where to listen (``port=0`` picks a free port; see :attr:`port`).
        versions: Protocol versions in the server's order of preference.
        ssl_context: Enables TLS (security profiles 2 and 3).
        known_id: ``known_id(charge_point_id)``; false answers HTTP 404.
        authenticate: ``authenticate(charge_point_id, password)``; when given,
            HTTP Basic auth is required and a wrong or missing one answers 401
            (security profiles 1 and 2).
        check_certificate_identity: Require the client certificate's CN to equal
            the charge point ID (profile 3); failure answers 403.
        operator_name: With the above, the certificate's O must contain this.
        ping_interval, ping_timeout: Keep-alive, defaults 30 s / 10 s.
        max_message_size: Largest accepted message in bytes (default 1 MiB).
        open_timeout, close_timeout: Handshake and close-handshake limits (10 s / 5 s).
    """

    def __init__(
        self,
        on_connect: OnConnect,
        *,
        on_disconnect: OnDisconnect | None = None,
        host: str = "127.0.0.1",
        port: int = 9000,
        versions: Sequence[Version] = (Version.OCPP21, Version.OCPP201, Version.OCPP16),
        ssl_context: ssl.SSLContext | None = None,
        known_id: Callable[[str], _MaybeAwaitable] | None = None,
        authenticate: Callable[[str, str], _MaybeAwaitable] | None = None,
        check_certificate_identity: bool = False,
        operator_name: str | None = None,
        ping_interval: float | None = 30.0,
        ping_timeout: float | None = 10.0,
        max_message_size: int = 1024 * 1024,
        open_timeout: float = 10.0,
        close_timeout: float = 5.0,
    ) -> None:
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._host = host
        self._port = port
        self._versions = tuple(versions)
        self._ssl = ssl_context
        self._known_id = known_id
        self._authenticate = authenticate
        self._check_cert = check_certificate_identity
        self._operator = operator_name
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._max_size = max_message_size
        self._open_timeout = open_timeout
        self._close_timeout = close_timeout
        self._server: WsServer | None = None
        self._connections: dict[str, Connection] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._closing = False

    # ------------------------------------------------------------ public API

    async def start(self) -> None:
        """Start listening."""
        self._server = await serve(
            self._handle,
            self._host,
            self._port,
            ssl=self._ssl,
            process_request=self._process_request,
            select_subprotocol=self._select_subprotocol,
            compression=None,
            ping_interval=self._ping_interval,
            ping_timeout=self._ping_timeout,
            max_size=self._max_size,
            open_timeout=self._open_timeout,
            close_timeout=self._close_timeout,
            logger=logging.getLogger("ocpp_sdk.transport.websockets"),
        )

    @property
    def port(self) -> int:
        """The port actually listening (useful with ``port=0``)."""
        assert self._server is not None, "server is not started"
        port: int = next(iter(self._server.sockets)).getsockname()[1]
        return port

    def charge_point_ids(self) -> list[str]:
        """IDs of the connected stations, in identity order."""
        return sorted(self._connections)

    def connection(self, charge_point_id: str) -> Connection | None:
        """The live connection of ``charge_point_id``, if any."""
        return self._connections.get(charge_point_id)

    async def shutdown(
        self,
        timeout: float = 10.0,  # noqa: ASYNC109 - public API takes a timeout
    ) -> None:
        """Stop accepting, close every connection with 1001 and wait up to ``timeout`` s."""
        self._closing = True
        server = self._server
        if server is None:
            return
        try:
            async with asyncio.timeout(timeout):
                await self._close_connections()
                server.close()
                await server.wait_closed()
        except TimeoutError:
            logger.warning("shutdown timed out after %ss", timeout)
            server.close()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _close_connections(self) -> None:
        """Close every connection with 1001 and wait for their handlers to finish.

        The listener stays open meanwhile, so a handshake that completes now
        is closed with 1001 as it registers.
        """
        await asyncio.gather(
            *(c.close(1001, "server is shutting down") for c in list(self._connections.values()))
        )
        while self._tasks:
            await asyncio.wait(list(self._tasks))

    async def __aenter__(self) -> Server:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.shutdown()

    # ------------------------------------------------------------- handshake

    def _select_subprotocol(
        self, connection: ServerConnection, offered: Sequence[Subprotocol]
    ) -> Subprotocol | None:
        for version in self._versions:
            if version.value in offered:
                return Subprotocol(version.value)
        return None

    async def _process_request(
        self, connection: ServerConnection, request: Request
    ) -> Response | None:
        charge_point_id = charge_point_id_from_path(request.path)
        if charge_point_id is None:
            return connection.respond(HTTPStatus.NOT_FOUND, "invalid charge point id\n")
        if self._known_id is not None and not await _resolve(self._known_id(charge_point_id)):
            return connection.respond(HTTPStatus.NOT_FOUND, "unknown charge point\n")
        if self._check_cert and not certificate_identity_ok(
            _peer_certificate(connection), charge_point_id, self._operator
        ):
            return connection.respond(HTTPStatus.FORBIDDEN, "certificate does not match\n")
        if self._authenticate is not None and not await self._basic_auth_ok(
            request.headers, charge_point_id
        ):
            response = connection.respond(HTTPStatus.UNAUTHORIZED, "authentication required\n")
            response.headers["WWW-Authenticate"] = 'Basic realm="OCPP", charset="UTF-8"'
            return response
        return None

    async def _basic_auth_ok(self, headers: Headers, charge_point_id: str) -> bool:
        assert self._authenticate is not None
        credentials = parse_basic_auth(headers.get("Authorization"))
        if credentials is None or credentials[0] != charge_point_id:
            return False
        return bool(await _resolve(self._authenticate(charge_point_id, credentials[1])))

    # ------------------------------------------------------------ connection

    async def _handle(self, ws: ServerConnection) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        try:
            await self._serve_connection(ws)
        finally:
            if task is not None:
                self._tasks.discard(task)

    async def _serve_connection(self, ws: ServerConnection) -> None:
        if self._closing:
            await ws.close(1001, "server is shutting down")
            return
        if ws.subprotocol is None:
            await ws.close(1002, "no matching OCPP subprotocol")
            return
        charge_point_id = charge_point_id_from_path(ws.request.path if ws.request else "")
        assert charge_point_id is not None  # checked in _process_request
        conn = Connection(ws, charge_point_id, Version(ws.subprotocol), _peer_certificate(ws))
        previous = self._connections.get(charge_point_id)
        self._connections[charge_point_id] = conn
        if previous is not None:
            logger.info("%s reconnected; closing the old connection", charge_point_id)
            self._spawn_close(previous)
        sink: FrameSink | None = None
        try:
            sink = await self._on_connect(conn)
            await self._receive(ws, sink)
        except ConnectionClosed:
            pass
        except Exception:
            logger.exception("connection of %s failed", charge_point_id)
            await ws.close(1011, "internal error")
        finally:
            if self._connections.get(charge_point_id) is conn:
                del self._connections[charge_point_id]
            if sink is not None:
                await sink.close()
            if self._on_disconnect is not None:
                await self._on_disconnect(conn)

    async def _receive(self, ws: ServerConnection, sink: FrameSink) -> None:
        async for message in ws:
            if isinstance(message, bytes):
                await ws.close(1003, "binary frames are not supported")
                return
            sink.feed(message)

    def _spawn_close(self, conn: Connection) -> None:
        task = asyncio.get_running_loop().create_task(_close_quietly(conn))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


async def _close_quietly(conn: Connection) -> None:
    await conn.close(1008, "replaced by a new connection")


def _peer_certificate(ws: ServerConnection) -> dict[str, Any] | None:
    ssl_object = ws.transport.get_extra_info("ssl_object")
    if ssl_object is None:
        return None
    certificate: dict[str, Any] | None = ssl_object.getpeercert()
    return certificate or None
