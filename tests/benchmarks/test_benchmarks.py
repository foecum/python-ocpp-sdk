"""Benchmarks (pytest-benchmark). Normal test runs only execute each once to check it works.

Measure with:

    uv run pytest tests/benchmarks --benchmark-enable --benchmark-only

There are no thresholds; results go in ``docs/benchmarks.md`` with the machine they ran on.
"""

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from ocpp_sdk.ocppj import Endpoint, Registry
from ocpp_sdk.ocppj.frames import Call, encode, parse_frame
from ocpp_sdk.v16 import csms as csms16
from ocpp_sdk.v16 import new_registry as registry16
from ocpp_sdk.v16.charge_point import ChargePoint
from ocpp_sdk.v16.core import HeartbeatConfirmation, HeartbeatRequest
from ocpp_sdk.v16.csms import CSMS
from ocpp_sdk.v16.csms_handlers import UnimplementedCoreHandler
from ocpp_sdk.v21 import new_registry as registry21
from ocpp_sdk.v201 import new_registry as registry201
from ocpp_sdk.versions import Version
from tests.schema import samples

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_201 = ROOT / "docs" / "spec" / "2.0.1" / "schemas"
SCHEMAS_21 = ROOT / "docs" / "spec" / "2.1" / "schemas"
FIXTURES_16 = ROOT / "tests" / "fixtures" / "v16"
REG16, REG201, REG21 = registry16(), registry201(), registry21()


def fixture16(action: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((FIXTURES_16 / f"{action}.json").read_text())["request"]
    return payload


def payload201(action: str) -> dict[str, Any]:
    _, payload = samples.load(SCHEMAS_201, f"{action}Request")
    assert isinstance(payload, dict)
    return payload


def payload21(stem: str) -> dict[str, Any]:
    _, payload = samples.load(SCHEMAS_21, stem)
    assert isinstance(payload, dict)
    return payload


# ------------------------------------------------------------------ framing and decoding


def test_parse_call_frame(benchmark: Any) -> None:
    raw = encode(Call("19223201", "BootNotification", fixture16("BootNotification")))
    benchmark(parse_frame, raw, Version.OCPP16)


def test_encode_call_frame(benchmark: Any) -> None:
    frame = Call("19223201", "BootNotification", fixture16("BootNotification"))
    benchmark(encode, frame)


@pytest.mark.parametrize("action", ["BootNotification", "MeterValues", "StartTransaction"])
def test_decode_v16(benchmark: Any, action: str) -> None:
    payload = fixture16(action)
    benchmark(REG16.decode_request, action, payload)


@pytest.mark.parametrize("action", ["BootNotification", "TransactionEvent", "NotifyReport"])
def test_decode_v201(benchmark: Any, action: str) -> None:
    payload = payload201(action)
    benchmark(REG201.decode_request, action, payload)


@pytest.mark.parametrize("action", ["BootNotification", "TransactionEvent", "SetChargingProfile"])
def test_decode_v21(benchmark: Any, action: str) -> None:
    payload = payload21(f"{action}Request")
    benchmark(REG21.decode_request, action, payload)


def test_decode_v21_send(benchmark: Any) -> None:
    payload = payload21("NotifyPeriodicEventStream")
    benchmark(REG21.decode_request, "NotifyPeriodicEventStream", payload)


def test_encode_v16_message(benchmark: Any) -> None:
    message = REG16.decode_request("MeterValues", fixture16("MeterValues"))
    benchmark(REG16.encode, message)


def test_encode_v201_message(benchmark: Any) -> None:
    message = REG201.decode_request("TransactionEvent", payload201("TransactionEvent"))
    benchmark(REG201.encode, message)


# ------------------------------------------------------------------ an endpoint pair, no network


@pytest.fixture
def runner() -> Iterator[asyncio.Runner]:
    with asyncio.Runner() as r:
        yield r


def test_complete_call_between_two_endpoints(benchmark: Any, runner: asyncio.Runner) -> None:
    holder: dict[str, Endpoint] = {}

    async def to_server(text: str) -> None:
        holder["server"].feed(text)

    async def to_client(text: str) -> None:
        holder["client"].feed(text)

    def handler(action: str, request: BaseModel) -> BaseModel:
        return HeartbeatConfirmation.model_validate({"currentTime": "2025-01-01T00:00:00Z"})

    async def setup() -> None:
        reg: Registry = registry16()
        holder["server"] = Endpoint(reg, to_client, handler=handler)
        holder["client"] = Endpoint(reg, to_server)

    runner.run(setup())

    def one_call() -> None:
        runner.run(holder["client"].call(HeartbeatRequest()))

    benchmark(one_call)
    runner.run(holder["client"].close())
    runner.run(holder["server"].close())


# ------------------------------------------------------------------ a CSMS with many stations

STATIONS = 50


def test_csms_with_many_stations(benchmark: Any, runner: asyncio.Runner) -> None:
    """One Heartbeat from each of 50 stations at once, over loopback WebSockets."""

    class Core(UnimplementedCoreHandler):
        def on_heartbeat(
            self, charge_point: Any, request: HeartbeatRequest
        ) -> HeartbeatConfirmation:
            return HeartbeatConfirmation.model_validate({"currentTime": "2025-01-01T00:00:00Z"})

    server = CSMS(csms16.Config(core=Core()), port=0, ping_interval=None)
    stations: list[ChargePoint] = []

    async def setup() -> None:
        await server.start()
        for i in range(STATIONS):
            station = ChargePoint(
                f"ws://127.0.0.1:{server.port}/ocpp/CP-{i}", ping_interval=None, reconnect=None
            )
            await station.__aenter__()
            stations.append(station)

    runner.run(setup())

    async def round_of_heartbeats() -> None:
        await asyncio.gather(*(s.heartbeat(HeartbeatRequest()) for s in stations))

    def run_round() -> None:
        runner.run(round_of_heartbeats())

    benchmark(run_round)

    async def teardown() -> None:
        await asyncio.gather(*(s.close() for s in stations))
        await server.shutdown(timeout=5)

    runner.run(teardown())
