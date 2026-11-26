"""An Endpoint on each side of a real WebSocket: full call round trips."""

import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from ocpp_sdk.errors import NotConnectedError
from ocpp_sdk.ocppj import Endpoint, Registry
from ocpp_sdk.transport import Client, Server
from ocpp_sdk.transport.connection import Connection
from ocpp_sdk.versions import Version
from tests.integration.helpers import until
from tests.unit.ocppj_models import (
    EchoRequest,
    EchoResponse,
    HeartbeatRequest,
    HeartbeatResponse,
)


def registry() -> Registry:
    reg = Registry(Version.OCPP201)
    reg.register(HeartbeatRequest, HeartbeatResponse)
    reg.register(EchoRequest, EchoResponse)
    return reg


def handler(action: str, request: BaseModel) -> BaseModel:
    if isinstance(request, EchoRequest):
        return EchoResponse(text=request.text.upper())
    return HeartbeatResponse(current_time=datetime(2025, 1, 1, tzinfo=UTC))


async def test_calls_both_ways_and_disconnect() -> None:
    csms_side: dict[str, Endpoint] = {}
    station_side: list[Endpoint] = []

    async def csms_connect(conn: Connection) -> Endpoint:
        ep = Endpoint(registry(), conn.send, handler=handler)
        csms_side[conn.charge_point_id] = ep
        return ep

    async def cp_connect(conn: Connection) -> Endpoint:
        ep = Endpoint(registry(), conn.send, handler=handler)
        station_side.append(ep)
        return ep

    async with Server(csms_connect, port=0) as server:
        async with Client(f"ws://127.0.0.1:{server.port}/ocpp/CP1", cp_connect):
            await until(lambda: "CP1" in csms_side)
            csms, station = csms_side["CP1"], station_side[0]
            assert await csms.call(EchoRequest(text="to station")) == EchoResponse(
                text="TO STATION"
            )
            assert await station.call(EchoRequest(text="to csms")) == EchoResponse(text="TO CSMS")
            results = await asyncio.gather(
                *(csms.call(EchoRequest(text=str(i))) for i in range(30)),
                *(station.call(EchoRequest(text=str(i))) for i in range(30)),
            )
            assert [r.text for r in results[:30]] == [str(i) for i in range(30)]  # type: ignore[attr-defined]
        await until(lambda: csms_side["CP1"].closed)
        with pytest.raises(NotConnectedError):
            await csms_side["CP1"].call(HeartbeatRequest())
        assert station_side[0].closed


async def test_disconnect_interrupts_a_call_in_flight() -> None:
    csms_side: dict[str, Endpoint] = {}
    started = asyncio.Event()

    async def hang(action: str, request: BaseModel) -> BaseModel:
        started.set()
        await asyncio.sleep(60)
        raise AssertionError("unreachable")

    async def csms_connect(conn: Connection) -> Endpoint:
        ep = Endpoint(registry(), conn.send, handler=handler)
        csms_side[conn.charge_point_id] = ep
        return ep

    async def cp_connect(conn: Connection) -> Endpoint:
        return Endpoint(registry(), conn.send, handler=hang)

    async with Server(csms_connect, port=0) as server:
        async with Client(f"ws://127.0.0.1:{server.port}/CP1", cp_connect) as client:
            await until(lambda: "CP1" in csms_side)
            call = asyncio.create_task(csms_side["CP1"].call(HeartbeatRequest()))
            await asyncio.wait_for(started.wait(), 3)
            assert client.connection is not None
            await client.connection.close()
        with pytest.raises(NotConnectedError):
            await call
