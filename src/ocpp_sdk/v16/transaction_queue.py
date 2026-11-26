"""OCPP 1.6 transaction message queue (spec section 3.7), opt-in and separate from ``ChargePoint``.

The application hands StartTransaction, StopTransaction and MeterValues to a
:class:`TransactionQueue`. It delivers them oldest first and waits while the station is offline
(that is not a failure). A message the Central System fails to process (a CALLERROR, a timeout or
an unusable answer) is retried up to ``attempts`` times, waiting ``retry_interval`` times the
number of earlier attempts, and is then dropped (``on_discard``).

A StartTransaction queued while offline returns a :class:`Transaction` handle. Messages queued with
that handle (``transaction=handle``) get the transactionId the Central System assigns, and are
dropped if the start was dropped. Persistence goes through a :class:`TransactionStore`; the
default keeps the queue in memory and :class:`FileStore` keeps it in an atomically written JSON
file, so it survives a restart.

Example:
    >>> from ocpp_sdk.v16.transaction_queue import MemoryStore, TransactionQueue
    >>> MemoryStore().load() is None
    True
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol

from pydantic import BaseModel

from ocpp_sdk.errors import CallError, CallTimeoutError, NotConnectedError, ValidationError
from ocpp_sdk.v16 import new_registry
from ocpp_sdk.v16.charge_point import ChargePoint
from ocpp_sdk.v16.core import (
    MeterValuesRequest,
    StartTransactionConfirmation,
    StartTransactionRequest,
    StopTransactionRequest,
)

__all__ = [
    "FileStore",
    "MemoryStore",
    "Transaction",
    "TransactionQueue",
    "TransactionStore",
]

logger = logging.getLogger("ocpp_sdk.v16.transaction_queue")

_REGISTRY = new_registry()
_KINDS = ("StartTransaction", "StopTransaction", "MeterValues")

DiscardHook = Callable[[str, BaseModel, str], Awaitable[None] | None]


class TransactionStore(Protocol):
    """Where a :class:`TransactionQueue` keeps its state between runs.

    The state is a JSON-compatible ``dict``; ``save`` is called after every change.
    """

    def load(self) -> dict[str, Any] | None:
        """The saved state, or ``None`` if there is none."""

    def save(self, state: dict[str, Any]) -> None:
        """Replace the saved state."""


class MemoryStore:
    """Keeps the state in memory only (the default).

    Example:
        >>> store = MemoryStore()
        >>> store.save({"a": 1})
        >>> store.load()
        {'a': 1}
    """

    def __init__(self) -> None:
        self._state: dict[str, Any] | None = None

    def load(self) -> dict[str, Any] | None:
        """The saved state, or ``None``."""
        return json.loads(json.dumps(self._state)) if self._state is not None else None

    def save(self, state: dict[str, Any]) -> None:
        """Replace the saved state."""
        self._state = json.loads(json.dumps(state))


class FileStore:
    """Keeps the state in a JSON file that is replaced atomically on every save.

    A file that cannot be read as JSON is treated as empty (and logged) instead of failing.

    Example:
        >>> import tempfile, pathlib
        >>> path = pathlib.Path(tempfile.mkdtemp()) / "queue.json"
        >>> store = FileStore(path)
        >>> store.save({"a": 1})
        >>> FileStore(path).load()
        {'a': 1}
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)

    def load(self) -> dict[str, Any] | None:
        """The saved state, or ``None`` if the file is missing or unreadable."""
        try:
            loaded = json.loads(self._path.read_text())
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            logger.exception("cannot read %s; starting with an empty queue", self._path)
            return None
        return loaded if isinstance(loaded, dict) else None

    def save(self, state: dict[str, Any]) -> None:
        """Write ``state`` to a temporary file, then rename it over the real one."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=self._path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(state, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise


@dataclass(eq=False)
class Transaction:
    """The handle of a queued StartTransaction.

    Attributes:
        transaction_id: The id the Central System assigned, once the start was delivered.
        dropped: The start was dropped, so nothing queued with it will be delivered.
    """

    local_id: int
    transaction_id: int | None = None
    dropped: bool = False
    _done: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    async def wait(self) -> int | None:
        """Wait until the start was delivered or dropped; returns the id (``None`` if dropped)."""
        await self._done.wait()
        return self.transaction_id


class TransactionQueue:
    """Delivers transaction messages in order, surviving offline periods.

    Args:
        charge_point: The station that sends them.
        store: Persistence; in memory by default.
        attempts: How many times a message is tried before it is dropped.
        retry_interval: Seconds; after the n-th failed attempt the wait is ``n`` times this.
        on_discard: ``on_discard(action, request, reason)`` for every dropped message (sync or
            async).
        response_timeout: Timeout of one delivery; the station's default if ``None``.
        sleep: Injection point for tests.

    Example:
        >>> async def main(cp: ChargePoint) -> None:  # doctest: +SKIP
        ...     async with TransactionQueue(cp, attempts=3, retry_interval=60) as queue:
        ...         handle = queue.start_transaction(StartTransactionRequest(...))
        ...         queue.stop_transaction(StopTransactionRequest(...), transaction=handle)
        ...         await queue.join()
    """

    def __init__(
        self,
        charge_point: ChargePoint,
        *,
        store: TransactionStore | None = None,
        attempts: int = 3,
        retry_interval: float = 60.0,
        on_discard: DiscardHook | None = None,
        response_timeout: float | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self._cp = charge_point
        self._store = store or MemoryStore()
        self._attempts = attempts
        self._retry_interval = retry_interval
        self._on_discard = on_discard
        self._timeout = response_timeout
        self._sleep = sleep
        self._items: list[dict[str, Any]] = []
        self._assigned: dict[str, int] = {}
        self._next = 1
        self._handles: dict[int, Transaction] = {}
        self._wakeup = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._task: asyncio.Task[None] | None = None
        self._load()

    # ------------------------------------------------------------------ public API

    @property
    def pending(self) -> int:
        """How many messages are waiting for delivery."""
        return len(self._items)

    def start_transaction(self, request: StartTransactionRequest) -> Transaction:
        """Queue a StartTransaction; returns the handle of the transaction it starts."""
        item = self._enqueue("StartTransaction", request, None)
        handle = Transaction(item["id"])
        self._handles[item["id"]] = handle
        return handle

    def stop_transaction(
        self, request: StopTransactionRequest, *, transaction: Transaction | None = None
    ) -> None:
        """Queue a StopTransaction.

        With ``transaction`` the handle's transactionId replaces the one in ``request`` when the
        message is delivered (pass any placeholder, such as ``0``).
        """
        self._enqueue("StopTransaction", request, transaction)

    def meter_values(
        self, request: MeterValuesRequest, *, transaction: Transaction | None = None
    ) -> None:
        """Queue a MeterValues message, optionally tied to a queued ``transaction``."""
        self._enqueue("MeterValues", request, transaction)

    def start(self) -> None:
        """Start delivering in the background (idempotent)."""
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def join(self) -> None:
        """Wait until the queue is empty (delivered or dropped)."""
        await self._idle.wait()

    async def close(self) -> None:
        """Stop delivering; what is still queued stays in the store."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def __aenter__(self) -> TransactionQueue:
        self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    # ------------------------------------------------------------------ state

    def _load(self) -> None:
        state = self._store.load()
        if not state:
            return
        self._items = [i for i in state.get("items", []) if i.get("kind") in _KINDS]
        self._assigned = {str(k): int(v) for k, v in state.get("assigned", {}).items()}
        self._next = int(state.get("next", 1))
        if self._items:
            self._idle.clear()

    def _save(self) -> None:
        live = {str(i["tx"]) for i in self._items if i["tx"] is not None}
        live |= {str(i["id"]) for i in self._items if i["kind"] == "StartTransaction"}
        self._assigned = {k: v for k, v in self._assigned.items() if k in live}
        self._store.save({"next": self._next, "items": self._items, "assigned": self._assigned})

    def _enqueue(
        self, kind: str, request: BaseModel, transaction: Transaction | None
    ) -> dict[str, Any]:
        if transaction is not None and transaction.dropped:
            raise ValueError("the transaction's StartTransaction was dropped")
        payload = _REGISTRY.encode(request)
        local = transaction.local_id if transaction is not None else None
        if transaction is not None and transaction.transaction_id is not None:
            payload["transactionId"] = transaction.transaction_id
            local = None
        item = {
            "id": self._next,
            "kind": kind,
            "payload": payload,
            "attempts": 0,
            "tx": local,
        }
        self._next += 1
        self._items.append(item)
        self._save()
        self._idle.clear()
        self._wakeup.set()
        return item

    # ------------------------------------------------------------------ delivery

    async def _run(self) -> None:
        while True:
            if not self._items:
                self._idle.set()
                self._wakeup.clear()
                await self._wakeup.wait()
                continue
            await self._cp.wait_online()
            await self._deliver(self._items[0])

    async def _deliver(self, item: dict[str, Any]) -> None:
        payload = dict(item["payload"])
        if item["tx"] is not None:
            assigned = self._assigned.get(str(item["tx"]))
            if assigned is None:  # the start was dropped (or lost): this message cannot be sent
                await self._discard(item, "the transaction's StartTransaction was dropped")
                return
            payload["transactionId"] = assigned
        request = _REGISTRY.decode_request(item["kind"], payload)
        try:
            answer = await self._send(item["kind"], request)
        except NotConnectedError:
            await asyncio.sleep(0)  # offline is not a failure: wait for the connection, retry
            return
        except (CallError, CallTimeoutError, ValidationError) as exc:
            item["attempts"] += 1
            if item["attempts"] >= self._attempts:
                await self._discard(item, f"failed {item['attempts']} times: {exc}")
            else:
                self._save()
                await self._sleep(self._retry_interval * item["attempts"])
            return
        if isinstance(answer, StartTransactionConfirmation):
            self._assigned[str(item["id"])] = answer.transaction_id
            handle = self._handles.pop(item["id"], None)
            if handle is not None:
                handle.transaction_id = answer.transaction_id
                handle._done.set()
        self._items.remove(item)
        self._save()

    async def _send(self, kind: str, request: BaseModel) -> BaseModel:
        if isinstance(request, StartTransactionRequest):
            return await self._cp.start_transaction(request, timeout=self._timeout)
        if isinstance(request, StopTransactionRequest):
            return await self._cp.stop_transaction(request, timeout=self._timeout)
        assert isinstance(request, MeterValuesRequest)
        return await self._cp.meter_values(request, timeout=self._timeout)

    async def _discard(self, item: dict[str, Any], reason: str) -> None:
        """Drop ``item`` (and, if it is a StartTransaction, everything queued with it)."""
        dropped = [item]
        if item["kind"] == "StartTransaction":
            dropped += [i for i in self._items if i["tx"] == item["id"]]
            handle = self._handles.pop(item["id"], None)
            if handle is not None:
                handle.dropped = True
                handle._done.set()
        for gone in dropped:
            self._items.remove(gone)
        self._save()
        for gone in dropped:
            why = reason if gone is item else "the transaction's StartTransaction was dropped"
            logger.warning("dropped %s: %s", gone["kind"], why)
            if self._on_discard is not None:
                request = _REGISTRY.decode_request(gone["kind"], gone["payload"])
                result = self._on_discard(gone["kind"], request, why)
                if inspect.isawaitable(result):
                    await result
