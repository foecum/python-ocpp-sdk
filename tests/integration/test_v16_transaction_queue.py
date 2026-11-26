"""The OCPP 1.6 transaction message queue against a real CSMS over loopback."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ocpp_sdk.errors import CallError
from ocpp_sdk.transport import Reconnect
from ocpp_sdk.v16 import csms as csms_module
from ocpp_sdk.v16.charge_point import ChargePoint
from ocpp_sdk.v16.core import (
    MeterValuesConfirmation,
    MeterValuesRequest,
    StartTransactionConfirmation,
    StartTransactionRequest,
    StopTransactionConfirmation,
    StopTransactionRequest,
)
from ocpp_sdk.v16.csms import CSMS
from ocpp_sdk.v16.csms import ChargePoint as Session
from ocpp_sdk.v16.csms_handlers import UnimplementedCoreHandler
from ocpp_sdk.v16.transaction_queue import (
    FileStore,
    MemoryStore,
    Transaction,
    TransactionQueue,
)
from ocpp_sdk.v16.types import AuthorizationStatus, IdTagInfo
from tests.integration.helpers import until

NOW = datetime(2025, 3, 14, 9, 26, 53, tzinfo=UTC)
ACCEPTED = IdTagInfo(status=AuthorizationStatus.ACCEPTED)


class Recorder(UnimplementedCoreHandler):
    """The Central System: records what it gets, can fail on demand."""

    def __init__(self) -> None:
        self.received: list[tuple[str, dict[str, Any]]] = []
        self.fail_next = 0
        self.fail_with = "InternalError"
        self.delay = 0.0
        self.next_id = 100

    async def _maybe_fail(self) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_next:
            self.fail_next -= 1
            raise CallError(self.fail_with, "try later")

    async def on_start_transaction(
        self, charge_point: Session, request: StartTransactionRequest
    ) -> StartTransactionConfirmation:
        self.received.append(("StartTransaction", request.model_dump(by_alias=True, mode="json")))
        await self._maybe_fail()
        self.next_id += 1
        return StartTransactionConfirmation(id_tag_info=ACCEPTED, transaction_id=self.next_id)

    async def on_stop_transaction(
        self, charge_point: Session, request: StopTransactionRequest
    ) -> StopTransactionConfirmation:
        self.received.append(("StopTransaction", request.model_dump(by_alias=True, mode="json")))
        await self._maybe_fail()
        return StopTransactionConfirmation()

    async def on_meter_values(
        self, charge_point: Session, request: MeterValuesRequest
    ) -> MeterValuesConfirmation:
        self.received.append(("MeterValues", request.model_dump(by_alias=True, mode="json")))
        await self._maybe_fail()
        return MeterValuesConfirmation()

    def kinds(self) -> list[str]:
        return [k for k, _ in self.received]


@pytest.fixture
async def world() -> AsyncIterator[tuple[CSMS, Recorder]]:
    recorder = Recorder()
    server = CSMS(csms_module.Config(core=recorder), port=0, ping_interval=None)
    await server.start()
    try:
        yield server, recorder
    finally:
        await server.shutdown(timeout=3)


def station(server: CSMS, **kwargs: Any) -> ChargePoint:
    kwargs.setdefault("reconnect", Reconnect(wait_minimum=0.05, random_range=0.0, repeat_times=1))
    return ChargePoint(f"ws://127.0.0.1:{server.port}/ocpp/CP-1", ping_interval=None, **kwargs)


def start(tag: str = "T") -> StartTransactionRequest:
    return StartTransactionRequest(connector_id=1, id_tag=tag, meter_start=0, timestamp=NOW)


def stop(tx: int = 0) -> StopTransactionRequest:
    return StopTransactionRequest(meter_stop=5, timestamp=NOW, transaction_id=tx)


def meter(tx: int | None = None) -> MeterValuesRequest:
    payload: dict[str, Any] = {
        "connectorId": 1,
        "meterValue": [{"timestamp": "2025-03-14T09:30:00Z", "sampledValue": [{"value": "1"}]}],
    }
    if tx is not None:
        payload["transactionId"] = tx
    return MeterValuesRequest.model_validate(payload)


async def test_messages_queued_offline_are_delivered_in_order_with_the_assigned_id(
    world: tuple[CSMS, Recorder],
) -> None:
    server, recorder = world
    cp = station(server)
    async with TransactionQueue(cp, retry_interval=0.01) as queue:
        handle = queue.start_transaction(start())
        queue.meter_values(meter(), transaction=handle)
        queue.stop_transaction(stop(), transaction=handle)
        assert queue.pending == 3 and handle.transaction_id is None
        await asyncio.sleep(0.1)
        assert recorder.received == []  # offline: nothing sent, nothing failed
        async with cp:
            await queue.join()
            assert await handle.wait() == 101
        assert recorder.kinds() == ["StartTransaction", "MeterValues", "StopTransaction"]
        assert recorder.received[1][1]["transactionId"] == 101
        assert recorder.received[2][1]["transactionId"] == 101
        assert queue.pending == 0


async def test_a_started_handle_tags_later_messages_directly(world: tuple[CSMS, Recorder]) -> None:
    server, recorder = world
    async with station(server) as cp, TransactionQueue(cp) as queue:
        handle = queue.start_transaction(start())
        await queue.join()
        queue.stop_transaction(stop(), transaction=handle)  # delivered already: id known
        queue.meter_values(meter(), transaction=handle)
        await queue.join()
        assert [r[1].get("transactionId") for r in recorder.received[1:]] == [101, 101]


async def test_failures_are_retried_with_growing_waits_then_dropped(
    world: tuple[CSMS, Recorder],
) -> None:
    server, recorder = world
    waits: list[float] = []
    dropped: list[tuple[str, str]] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    def on_discard(kind: str, request: Any, reason: str) -> None:
        dropped.append((kind, reason))

    async with station(server) as cp:
        queue = TransactionQueue(
            cp, attempts=3, retry_interval=10.0, on_discard=on_discard, sleep=fake_sleep
        )
        async with queue:
            recorder.fail_next = 2
            queue.meter_values(meter())
            await queue.join()
            assert waits == [10.0, 20.0] and recorder.kinds() == ["MeterValues"] * 3
            assert dropped == []

            waits.clear()
            recorder.received.clear()
            recorder.fail_next = 99
            queue.meter_values(meter())
            queue.stop_transaction(stop(5))  # behind the failing one: waits its turn
            recorder.fail_next = 3
            await queue.join()
            assert waits == [10.0, 20.0]
            assert [k for k, _ in dropped] == ["MeterValues"]
            assert "failed 3 times" in dropped[0][1] and "InternalError" in dropped[0][1]
            assert recorder.kinds() == ["MeterValues"] * 3 + ["StopTransaction"]


async def test_timeouts_count_as_failures(world: tuple[CSMS, Recorder]) -> None:
    server, recorder = world
    recorder.delay = 0.3
    dropped: list[str] = []

    async def on_discard(kind: str, request: Any, reason: str) -> None:
        dropped.append(kind)

    async with station(server) as cp:
        async with TransactionQueue(
            cp, attempts=2, retry_interval=0.01, response_timeout=0.05, on_discard=on_discard
        ) as queue:
            queue.meter_values(meter())
            await queue.join()
    assert dropped == ["MeterValues"]
    assert len(recorder.received) == 2


async def test_a_dropped_start_drops_everything_queued_with_it(
    world: tuple[CSMS, Recorder],
) -> None:
    server, recorder = world
    recorder.fail_next = 99
    dropped: list[tuple[str, str]] = []
    async with station(server) as cp:
        async with TransactionQueue(
            cp,
            attempts=2,
            retry_interval=0.01,
            on_discard=lambda kind, req, why: dropped.append((kind, why)),
        ) as queue:
            handle = queue.start_transaction(start())
            queue.meter_values(meter(), transaction=handle)
            queue.stop_transaction(stop(), transaction=handle)
            other = queue.meter_values  # an unrelated message behind them is still sent
            assert await handle.wait() is None and handle.dropped
            recorder.fail_next = 0
            other(meter(7))
            await queue.join()
            with pytest.raises(ValueError, match="dropped"):
                queue.stop_transaction(stop(), transaction=handle)
    assert [k for k, _ in dropped] == ["StartTransaction", "MeterValues", "StopTransaction"]
    assert dropped[1][1] == "the transaction's StartTransaction was dropped"
    assert recorder.kinds() == ["StartTransaction"] * 2 + ["MeterValues"]


async def test_the_connection_dropping_mid_delivery_is_not_a_failure(
    world: tuple[CSMS, Recorder],
) -> None:
    server, recorder = world
    recorder.delay = 0.2
    dropped: list[str] = []
    async with station(server) as cp:
        async with TransactionQueue(
            cp, attempts=1, on_discard=lambda kind, req, why: dropped.append(kind)
        ) as queue:
            queue.meter_values(meter())
            await until(lambda: len(recorder.received) == 1)
            first = cp.connection
            assert first is not None
            await first.close(1012, "restart")
            recorder.delay = 0
            await queue.join()
    assert dropped == []  # attempts=1 would have dropped it had the lost link counted
    assert recorder.kinds() == ["MeterValues", "MeterValues"]


async def test_the_queue_survives_a_restart_in_a_file(
    world: tuple[CSMS, Recorder], tmp_path: Path
) -> None:
    server, recorder = world
    path = tmp_path / "state" / "queue.json"
    cp = station(server)
    queue = TransactionQueue(cp, store=FileStore(path))
    handle = queue.start_transaction(start())
    queue.meter_values(meter(), transaction=handle)
    queue.stop_transaction(stop(), transaction=handle)
    assert json.loads(path.read_text())["next"] == 4
    await queue.close()  # "restart": a new process reads the file
    assert not list(path.parent.glob("*.tmp"))

    cp2 = station(server)
    async with TransactionQueue(cp2, store=FileStore(path)) as queue2, cp2:
        assert queue2.pending == 3
        await queue2.join()
    assert recorder.kinds() == ["StartTransaction", "MeterValues", "StopTransaction"]
    assert recorder.received[2][1]["transactionId"] == 101
    assert json.loads(path.read_text()) == {"next": 4, "items": [], "assigned": {}}


async def test_close_keeps_the_rest_in_the_store(world: tuple[CSMS, Recorder]) -> None:
    server, _ = world
    store = MemoryStore()
    cp = station(server)
    queue = TransactionQueue(cp, store=store)
    queue.meter_values(meter())
    await queue.close()  # never started: close is harmless
    queue.start()
    queue.start()  # idempotent
    await queue.close()
    state = store.load()
    assert state is not None and len(state["items"]) == 1
    assert TransactionQueue(cp, store=store).pending == 1


async def test_a_message_whose_start_is_unknown_is_dropped(world: tuple[CSMS, Recorder]) -> None:
    server, recorder = world
    store = MemoryStore()
    store.save(
        {
            "next": 3,
            "items": [
                {"id": 1, "kind": "Bogus", "payload": {}, "attempts": 0, "tx": None},
                {
                    "id": 2,
                    "kind": "MeterValues",
                    "payload": meter().model_dump(by_alias=True, mode="json"),
                    "attempts": 0,
                    "tx": 99,
                },
            ],
            "assigned": {},
        }
    )
    dropped: list[str] = []
    async with station(server) as cp:
        queue = TransactionQueue(cp, store=store, on_discard=lambda k, r, why: dropped.append(why))
        assert queue.pending == 1  # the unknown kind was ignored on load
        async with queue:
            await queue.join()
    assert dropped == ["the transaction's StartTransaction was dropped"]
    assert recorder.received == []


def test_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    memory = MemoryStore()
    assert memory.load() is None
    state = {"next": 1, "items": []}
    memory.save(state)
    state["next"] = 2  # the store holds its own copy
    assert memory.load() == {"next": 1, "items": []}

    file_store = FileStore(tmp_path / "a.json")
    assert file_store.load() is None
    (tmp_path / "a.json").write_text("{broken")
    assert file_store.load() is None
    (tmp_path / "a.json").write_text("[1, 2]")
    assert file_store.load() is None
    file_store.save({"next": 5})
    assert FileStore(tmp_path / "a.json").load() == {"next": 5}

    def failing_replace(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError, match="disk full"):
        file_store.save({"next": 6})
    monkeypatch.undo()
    assert FileStore(tmp_path / "a.json").load() == {"next": 5}  # the old file is intact
    assert not list(tmp_path.glob("*.tmp"))


def test_store_read_errors_are_logged_not_raised(tmp_path: Path) -> None:
    directory = tmp_path / "dir"
    directory.mkdir()
    assert FileStore(directory).load() is None  # reading a directory fails with OSError


def test_attempts_must_be_positive(world: tuple[CSMS, Recorder]) -> None:
    with pytest.raises(ValueError, match="attempts"):
        TransactionQueue(ChargePoint("ws://localhost:9/CP-1"), attempts=0)


async def test_transaction_handle_repr_and_wait() -> None:
    handle = Transaction(local_id=1)
    assert "transaction_id=None" in repr(handle)
    waiter = asyncio.create_task(handle.wait())
    await asyncio.sleep(0)
    assert not waiter.done()
    handle.dropped = True
    handle._done.set()
    assert await waiter is None


async def test_an_empty_saved_state_and_a_restored_start_without_a_hook(
    world: tuple[CSMS, Recorder],
) -> None:
    server, recorder = world
    store = MemoryStore()
    store.save({"next": 9, "items": [], "assigned": {}})
    cp = station(server)
    assert TransactionQueue(cp, store=store).pending == 0

    # a start that was restored from a file has no handle and no on_discard hook
    recorder.fail_next = 99
    queue = TransactionQueue(cp, store=store, attempts=1)
    queue.start_transaction(start())
    queue2 = TransactionQueue(cp, store=store, attempts=1)  # reads the saved start
    assert queue2.pending == 1
    async with cp, queue2:
        await queue2.join()
    assert recorder.kinds() == ["StartTransaction"]
