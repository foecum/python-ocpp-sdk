"""Transport-agnostic OCPP-J endpoint: correlation, timeouts, queueing, dispatch.

The transport gives the endpoint a ``send`` coroutine and passes every text
frame it receives to :meth:`Endpoint.feed`. One endpoint serves one
connection; when the connection ends, call :meth:`Endpoint.close` and create
a new endpoint for the next connection.

Example:
    >>> import asyncio
    >>> from ocpp_sdk.ocppj.endpoint import Endpoint
    >>> from ocpp_sdk.ocppj.registry import Registry
    >>> from ocpp_sdk.versions import Version
    >>> async def demo() -> None:
    ...     async def send(text: str) -> None: ...
    ...     async with Endpoint(Registry(Version.OCPP16), send):
    ...         pass
    >>> asyncio.run(demo())
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from types import TracebackType
from typing import Any

from pydantic import BaseModel

from ocpp_sdk.errors import (
    CallError,
    CallTimeoutError,
    NotConnectedError,
    QueueFullError,
    ValidationError,
    code_for_version,
)
from ocpp_sdk.ocppj.frames import (
    Call,
    CallErrorFrame,
    CallResult,
    Frame,
    FrameError,
    encode,
    parse_frame,
)
from ocpp_sdk.ocppj.registry import Registry

__all__ = ["DEFAULT_QUEUE_SIZE", "DEFAULT_RESPONSE_TIMEOUT", "Endpoint", "Handler", "Send"]

logger = logging.getLogger("ocpp_sdk.ocppj.endpoint")

DEFAULT_RESPONSE_TIMEOUT = 30.0
DEFAULT_QUEUE_SIZE = 1000

Send = Callable[[str], Awaitable[None]]
Handler = Callable[[str, BaseModel], BaseModel | Awaitable[BaseModel]]


@dataclass(eq=False, slots=True)
class _Pending:
    unique_id: str
    action: str
    text: str
    timeout: float
    future: asyncio.Future[BaseModel]


class Endpoint:
    """One side of an OCPP-J connection.

    Args:
        registry: The actions of the connection's protocol version.
        send: Coroutine that writes one text frame to the connection.
        handler: Called as ``handler(action, request)`` for every valid
            incoming CALL; returns the response model (sync or async). Raise
            :class:`~ocpp_sdk.errors.CallError` to answer with a specific
            CALLERROR; any other exception is answered with ``InternalError``
            (its text is never sent). Without a handler every CALL is
            answered ``NotImplemented``.
        response_timeout: Default seconds to wait for a response, counted
            from the moment the CALL is sent.
        queue_size: How many calls may wait behind the outstanding one.
        id_factory: Produces message IDs (at most 36 characters).
    """

    def __init__(
        self,
        registry: Registry,
        send: Send,
        *,
        handler: Handler | None = None,
        response_timeout: float = DEFAULT_RESPONSE_TIMEOUT,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._registry = registry
        self._send = send
        self._handler = handler
        self._timeout = response_timeout
        self._queue_size = queue_size
        self._new_id = id_factory or (lambda: str(uuid.uuid4()))
        self._queue: deque[_Pending] = deque()
        self._outstanding: _Pending | None = None
        self._wakeup = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self._worker: asyncio.Task[None] | None = None
        self._closed = False

    async def __aenter__(self) -> Endpoint:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    @property
    def closed(self) -> bool:
        """Whether :meth:`close` has been called."""
        return self._closed

    # ------------------------------------------------------------------ calls

    async def call(
        self,
        request: BaseModel,
        *,
        timeout: float | None = None,  # noqa: ASYNC109 - per-call timeout is the public API
    ) -> BaseModel:
        """Send a CALL and wait for its response.

        Calls are sent one at a time, oldest first.

        Raises:
            ValidationError: The request is invalid, or the response is.
            NotConnectedError: The endpoint is closed, the send failed, or the
                connection was lost before the response arrived.
            QueueFullError: Too many calls are already waiting.
            CallTimeoutError: No response within ``timeout`` seconds.
            CallError: The peer answered with a CALLERROR.
        """
        if self._closed:
            raise NotConnectedError("endpoint is closed")
        action = type(request).ACTION  # type: ignore[attr-defined]
        payload = self._registry.encode(request)
        if len(self._queue) >= self._queue_size:
            raise QueueFullError(f"{self._queue_size} calls are already waiting")
        unique_id = self._new_id()
        pending = _Pending(
            unique_id=unique_id,
            action=action,
            text=encode(Call(unique_id, action, payload)),
            timeout=self._timeout if timeout is None else timeout,
            future=asyncio.get_running_loop().create_future(),
        )
        self._queue.append(pending)
        if self._worker is None:
            self._worker = self._spawn(self._run_calls())
        self._wakeup.set()
        try:
            return await pending.future
        except asyncio.CancelledError:
            if pending in self._queue:
                self._queue.remove(pending)
            raise

    async def _run_calls(self) -> None:
        while True:
            while not self._queue:
                self._wakeup.clear()
                await self._wakeup.wait()
            pending = self._queue.popleft()
            if pending.future.done():
                continue
            self._outstanding = pending
            try:
                await self._send_outstanding(pending)
            finally:
                self._outstanding = None

    async def _send_outstanding(self, pending: _Pending) -> None:
        try:
            await self._write(pending.text)
        except Exception as exc:
            _fail(pending, NotConnectedError(f"send failed: {exc}"))
            return
        await asyncio.wait({pending.future}, timeout=pending.timeout)
        _fail(pending, CallTimeoutError(f"no response to {pending.action} in {pending.timeout}s"))

    async def _write(self, text: str) -> None:
        async with self._write_lock:
            await self._send(text)

    # --------------------------------------------------------------- incoming

    def feed(self, raw: str) -> None:
        """Handle one text frame received from the connection.

        Returns immediately; CALLs are handled in their own task. Must be
        called from the running event loop.
        """
        if self._closed:
            return
        try:
            frame = parse_frame(raw, self._registry.version)
        except FrameError as err:
            self._on_frame_error(err)
            return
        if isinstance(frame, Call):
            self._spawn(self._handle_call(frame))
        elif isinstance(frame, CallResult):
            self._on_result(frame)
        else:
            self._on_call_error(frame)

    def _matching(self, unique_id: str) -> _Pending | None:
        pending = self._outstanding
        if pending is None or pending.unique_id != unique_id or pending.future.done():
            logger.debug("dropping response with unknown or late id %s", unique_id)
            return None
        return pending

    def _on_frame_error(self, err: FrameError) -> None:
        if err.message_type in (3, 4):
            pending = self._matching(err.unique_id)
            if pending is not None:
                _fail(pending, ValidationError(f"unusable response: {err.description}"))
            return
        if not err.reply:
            logger.warning("ignoring frame: %s", err)
            return
        reply = CallErrorFrame(
            err.unique_id, code_for_version(err.code, self._registry.version), err.description
        )
        self._spawn(self._reply(reply))

    def _on_result(self, frame: CallResult) -> None:
        pending = self._matching(frame.unique_id)
        if pending is None:
            return
        try:
            pending.future.set_result(self._registry.decode_response(pending.action, frame.payload))
        except ValidationError as exc:
            pending.future.set_exception(exc)

    def _on_call_error(self, frame: CallErrorFrame) -> None:
        pending = self._matching(frame.unique_id)
        if pending is not None:
            pending.future.set_exception(CallError(frame.code, frame.description, frame.details))

    async def _handle_call(self, frame: Call) -> None:
        await self._reply(await self._answer(frame))

    async def _answer(self, frame: Call) -> Frame:
        version = self._registry.version
        try:
            request = self._registry.decode_request(frame.action, frame.payload)
            if self._handler is None:
                raise CallError("NotImplemented", "no handler is installed")
            result = self._handler(frame.action, request)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, self._registry.response_type(frame.action)):
                raise TypeError(f"handler returned {type(result).__name__}")
            return CallResult(frame.unique_id, self._registry.encode(result))
        except CallError as err:
            return CallErrorFrame(
                frame.unique_id,
                code_for_version(err.code, version),
                err.description,
                err.details,
            )
        except Exception:
            logger.exception("handler for %s failed", frame.action)
            return CallErrorFrame(frame.unique_id, "InternalError")

    async def _reply(self, frame: Frame) -> None:
        try:
            await self._write(encode(frame))
        except Exception as exc:
            logger.debug("could not send reply %s: %s", frame.unique_id, exc)

    # --------------------------------------------------------------- lifecycle

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def close(self) -> None:
        """Fail every waiting call with ``NotConnectedError`` and stop all tasks.

        Safe to call more than once, and from inside a handler.
        """
        if not self._closed:
            self._closed = True
            error = NotConnectedError("connection closed")
            for pending in [*self._queue, self._outstanding]:
                if pending is not None:
                    _fail(pending, error)
            self._queue.clear()
        current = asyncio.current_task()
        tasks = [t for t in self._tasks if t is not current]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _fail(pending: _Pending, error: Exception) -> None:
    if not pending.future.done():
        pending.future.set_exception(error)
