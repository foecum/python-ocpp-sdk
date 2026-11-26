"""Shared helpers for transport tests."""

import asyncio
from collections.abc import Awaitable, Callable

from ocpp_sdk.transport.connection import Connection


class RecordingSink:
    """A FrameSink that records frames and can echo them back."""

    def __init__(self, conn: Connection, echo: bool = False) -> None:
        self.conn = conn
        self.frames: list[str] = []
        self.closed = asyncio.Event()
        self._echo = echo
        self._tasks: set[asyncio.Task[None]] = set()

    def feed(self, raw: str) -> None:
        self.frames.append(raw)
        if self._echo:
            task = asyncio.get_running_loop().create_task(self.conn.send(raw))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def close(self) -> None:
        self.closed.set()


class Sinks:
    """on_connect factory that remembers every sink it made."""

    def __init__(self, echo: bool = False) -> None:
        self.sinks: list[RecordingSink] = []
        self.disconnected: list[Connection] = []
        self._echo = echo
        self.connected = asyncio.Event()

    async def on_connect(self, conn: Connection) -> RecordingSink:
        sink = RecordingSink(conn, self._echo)
        self.sinks.append(sink)
        self.connected.set()
        return sink

    async def on_disconnect(self, conn: Connection) -> None:
        self.disconnected.append(conn)


async def until(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


async def maybe(value: Awaitable[None] | None) -> None:
    if value is not None:
        await value
