"""WebSocket client for charge points, with OCPP-J section 5.4 reconnect.

Example:
    >>> from ocpp_sdk.transport.client import Reconnect
    >>> Reconnect(wait_minimum=1, random_range=0).delay(0), Reconnect(1, 0).delay(2)
    (1.0, 4.0)
"""

from __future__ import annotations

import asyncio
import logging
import random
import ssl
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from types import TracebackType

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.typing import Subprotocol

from ocpp_sdk.errors import NotConnectedError
from ocpp_sdk.transport.auth import basic_auth_header, charge_point_id_from_path
from ocpp_sdk.transport.connection import Connection, FrameSink
from ocpp_sdk.versions import Version

__all__ = ["Client", "OnConnect", "Reconnect"]

logger = logging.getLogger("ocpp_sdk.transport.client")

OnConnect = Callable[[Connection], Awaitable[FrameSink]]


@dataclass(frozen=True, slots=True)
class Reconnect:
    """Back-off of OCPP-J section 5.4 (names as in the spec).

    The wait is ``wait_minimum`` plus a random value up to ``random_range``,
    and it doubles after each failure, ``repeat_times`` times in all.

    Example:
        >>> Reconnect(wait_minimum=10, random_range=0, repeat_times=2).delay(5)
        40.0
    """

    wait_minimum: float = 1.0
    random_range: float = 2.0
    repeat_times: int = 6

    def delay(self, failures: int, rng: Callable[[], float] = random.random) -> float:
        """Seconds to wait after ``failures`` earlier waits in a row (0 = the first wait)."""
        doublings = min(failures, self.repeat_times)
        return float((self.wait_minimum + rng() * self.random_range) * 2**doublings)


class Client:
    """Connects to a CSMS and keeps the connection up.

    Args:
        url: ``ws://`` or ``wss://`` URL ending in the charge point ID.
        on_connect: Called for every established connection; returns the sink
            (usually an ``Endpoint``) that receives its frames. The sink is
            closed when the connection ends.
        versions: Subprotocols to offer, in the client's order of preference.
        password: HTTP Basic password (the username is the charge point ID).
        ssl_context: TLS context for ``wss://`` (profiles 2 and 3).
        reconnect: Back-off settings; ``None`` disables reconnecting (one attempt).
        ping_interval, ping_timeout: Keep-alive, defaults 30 s / 10 s.
        max_message_size: Largest accepted message in bytes (default 1 MiB).
        open_timeout, close_timeout: Handshake and close-handshake limits (10 s / 5 s).
        sleep, rng: Injection points for tests.
    """

    def __init__(
        self,
        url: str,
        on_connect: OnConnect,
        *,
        versions: Sequence[Version] = (Version.OCPP201,),
        password: str | None = None,
        ssl_context: ssl.SSLContext | None = None,
        reconnect: Reconnect | None = Reconnect(),
        ping_interval: float | None = 30.0,
        ping_timeout: float | None = 10.0,
        max_message_size: int = 1024 * 1024,
        open_timeout: float = 10.0,
        close_timeout: float = 5.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        charge_point_id = charge_point_id_from_path(url.split("://", 1)[-1].partition("/")[2])
        if charge_point_id is None:
            raise ValueError("the URL must end with a valid charge point ID")
        self._url = url
        self._id = charge_point_id
        self._on_connect = on_connect
        self._versions = tuple(versions)
        self._password = password
        self._ssl = ssl_context
        self._reconnect = reconnect
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._max_size = max_message_size
        self._open_timeout = open_timeout
        self._close_timeout = close_timeout
        self._sleep = sleep
        self._rng = rng
        self._task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()
        self._finished = asyncio.Event()
        self._connection: Connection | None = None
        self._last_error: Exception | None = None
        self._closing = False

    @property
    def connection(self) -> Connection | None:
        """The live connection, or ``None`` while disconnected."""
        return self._connection

    def start(self) -> None:
        """Start connecting in the background (idempotent)."""
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def wait_connected(
        self,
        timeout: float | None = None,  # noqa: ASYNC109 - public API takes a timeout
    ) -> Connection:
        """Wait until connected.

        Raises:
            NotConnectedError: The client gave up (reconnect disabled) or was closed.
            TimeoutError: Not connected within ``timeout`` seconds.
        """
        async with asyncio.timeout(timeout):
            while self._connection is None:
                if self._finished.is_set():
                    raise NotConnectedError(f"not connected: {self._last_error}") from (
                        self._last_error
                    )
                self._connected.clear()
                waiters = [
                    asyncio.ensure_future(self._connected.wait()),
                    asyncio.ensure_future(self._finished.wait()),
                ]
                try:
                    await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for waiter in waiters:
                        waiter.cancel()
        return self._connection

    async def close(self) -> None:
        """Close the connection and stop reconnecting."""
        self._closing = True
        task = self._task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._finished.set()

    async def __aenter__(self) -> Client:
        self.start()
        await self.wait_connected()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    # ------------------------------------------------------------ supervisor

    async def _run(self) -> None:
        waits = 0
        try:
            while not self._closing:
                try:
                    if await self._session():
                        waits = 0
                except (OSError, WebSocketException, TimeoutError) as exc:
                    self._last_error = exc
                    logger.warning("connection attempt failed: %s", exc)
                if self._reconnect is None:
                    return
                delay = self._reconnect.delay(waits, self._rng)
                waits += 1
                logger.info("reconnecting in %.1fs", delay)
                await self._sleep(delay)
        finally:
            self._connection = None
            self._finished.set()

    async def _session(self) -> bool:
        """One connection from handshake to close; True if it was established."""
        headers = (
            {"Authorization": basic_auth_header(self._id, self._password)}
            if self._password is not None
            else None
        )
        async with connect(
            self._url,
            subprotocols=[Subprotocol(v.value) for v in self._versions],
            additional_headers=headers,
            ssl=self._ssl,
            compression=None,
            ping_interval=self._ping_interval,
            ping_timeout=self._ping_timeout,
            max_size=self._max_size,
            open_timeout=self._open_timeout,
            close_timeout=self._close_timeout,
            proxy=None,
            logger=logging.getLogger("ocpp_sdk.transport.websockets"),
        ) as ws:
            if ws.subprotocol is None:
                self._last_error = NotConnectedError("no common OCPP subprotocol")
                logger.warning("the server chose no OCPP subprotocol")
                await ws.close(1002, "no matching OCPP subprotocol")
                return False
            conn = Connection(ws, self._id, Version(ws.subprotocol))
            sink = await self._on_connect(conn)
            self._connection = conn
            self._connected.set()
            try:
                await self._receive(ws, sink)
            except ConnectionClosed:
                pass
            finally:
                self._connection = None
                await sink.close()
            return True

    async def _receive(self, ws: ClientConnection, sink: FrameSink) -> None:
        async for message in ws:
            if isinstance(message, bytes):
                await ws.close(1003, "binary frames are not supported")
                return
            sink.feed(message)
