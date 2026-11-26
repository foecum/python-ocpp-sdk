import asyncio
import base64
import logging
import os
from typing import Any

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.typing import Subprotocol

from ocpp_sdk.transport import Server
from ocpp_sdk.transport.auth import basic_auth_header
from ocpp_sdk.versions import Version
from tests.integration.helpers import Sinks, until


def sp(*names: str) -> list[Subprotocol]:
    return [Subprotocol(n) for n in names]


def url(server: Server, path: str = "CP1") -> str:
    return f"ws://127.0.0.1:{server.port}/ocpp/{path}"


def make(sinks: Sinks, **kwargs: Any) -> Server:
    return Server(sinks.on_connect, on_disconnect=sinks.on_disconnect, port=0, **kwargs)


async def test_echo_and_registry() -> None:
    sinks = Sinks(echo=True)
    async with make(sinks) as server:
        async with connect(url(server), subprotocols=sp("ocpp2.0.1")) as ws:
            assert ws.subprotocol == "ocpp2.0.1"
            await ws.send("hello")
            assert await ws.recv() == "hello"
            assert server.charge_point_ids() == ["CP1"]
            conn = server.connection("CP1")
            assert conn is not None
            assert (conn.charge_point_id, conn.version) == ("CP1", Version.OCPP201)
            assert conn.peer_certificate is None
        await until(lambda: sinks.disconnected != [])
        assert sinks.sinks[0].closed.is_set()
        assert server.charge_point_ids() == []
        assert server.connection("CP1") is None


async def test_compression_is_not_negotiated() -> None:
    sinks = Sinks()
    async with make(sinks) as server:
        async with connect(url(server), subprotocols=sp("ocpp1.6"), compression="deflate") as ws:
            assert ws.response is not None
            assert ws.response.headers.get("Sec-WebSocket-Extensions") is None


@pytest.mark.parametrize(
    ("offered", "preference", "chosen"),
    [
        (["ocpp1.6", "ocpp2.0.1"], (Version.OCPP201, Version.OCPP16), "ocpp2.0.1"),
        (["ocpp2.0.1", "ocpp1.6"], (Version.OCPP16, Version.OCPP201), "ocpp1.6"),
        (["ocpp2.1", "ocpp1.6"], (Version.OCPP16, Version.OCPP21), "ocpp1.6"),
        (["ocpp2.1", "ocpp1.6", "ocpp2.0.1"], (Version.OCPP21, Version.OCPP201), "ocpp2.1"),
    ],
)
async def test_server_preference_decides_the_version(
    offered: list[str], preference: tuple[Version, ...], chosen: str
) -> None:
    sinks = Sinks()
    async with make(sinks, versions=preference) as server:
        async with connect(url(server), subprotocols=sp(*offered) if offered else None) as ws:
            assert ws.subprotocol == chosen


@pytest.mark.parametrize("offered", [["ocpp2.1"], ["something-else"], []])
async def test_subprotocol_mismatch_closes_with_1002(offered: list[str]) -> None:
    sinks = Sinks()
    async with make(sinks, versions=(Version.OCPP16,)) as server:
        async with connect(url(server), subprotocols=sp(*offered) if offered else None) as ws:
            assert ws.subprotocol is None
            with pytest.raises(ConnectionClosed):
                await ws.recv()
            assert ws.protocol.close_code == 1002
        assert sinks.sinks == []


@pytest.mark.parametrize(
    "path",
    ["", "a%3Ab", "a%2Fb", "x" * 49],
)
async def test_invalid_id_is_404(path: str) -> None:
    sinks = Sinks()
    async with make(sinks) as server:
        with pytest.raises(InvalidStatus) as info:
            async with connect(url(server, path), subprotocols=sp("ocpp1.6")):
                pass
        assert info.value.response.status_code == 404


async def test_long_id_boundary_is_accepted() -> None:
    sinks = Sinks()
    async with make(sinks) as server:
        async with connect(url(server, "x" * 48), subprotocols=sp("ocpp1.6")):
            await until(lambda: server.charge_point_ids() == ["x" * 48])


@pytest.mark.parametrize("is_async", [False, True])
async def test_unknown_id_is_404(is_async: bool) -> None:
    sinks = Sinks()

    async def known_async(cp: str) -> bool:
        return cp == "CP1"

    def known_sync(cp: str) -> bool:
        return cp == "CP1"

    async with make(sinks, known_id=known_async if is_async else known_sync) as server:
        with pytest.raises(InvalidStatus) as info:
            async with connect(url(server, "CP9"), subprotocols=sp("ocpp1.6")):
                pass
        assert info.value.response.status_code == 404
        async with connect(url(server, "CP1"), subprotocols=sp("ocpp1.6")):
            pass


@pytest.mark.parametrize("is_async", [False, True])
async def test_basic_auth(is_async: bool) -> None:
    sinks = Sinks()

    async def check_async(cp: str, password: str) -> bool:
        return password == "secret"

    def check_sync(cp: str, password: str) -> bool:
        return password == "secret"

    async with make(sinks, authenticate=check_async if is_async else check_sync) as server:
        bad: list[dict[str, str] | None] = [
            None,
            {"Authorization": basic_auth_header("CP1", "wrong")},
            {"Authorization": basic_auth_header("OTHER", "secret")},
            {"Authorization": "Bearer abc"},
        ]
        for headers in bad:
            with pytest.raises(InvalidStatus) as info:
                async with connect(
                    url(server),
                    subprotocols=sp("ocpp1.6"),
                    additional_headers=headers,
                ):
                    pass
            assert info.value.response.status_code == 401
            assert "Basic" in info.value.response.headers["WWW-Authenticate"]
        good = {"Authorization": basic_auth_header("CP1", "secret")}
        async with connect(url(server), subprotocols=sp("ocpp1.6"), additional_headers=good) as ws:
            assert ws.subprotocol == "ocpp1.6"


async def test_duplicate_id_replaces_the_old_connection_with_1008() -> None:
    sinks = Sinks()
    async with make(sinks) as server:
        async with connect(url(server), subprotocols=sp("ocpp1.6")) as old:
            await until(lambda: len(sinks.sinks) == 1)
            async with connect(url(server), subprotocols=sp("ocpp1.6")) as new:
                with pytest.raises(ConnectionClosed):
                    await old.recv()
                assert old.protocol.close_code == 1008
                await until(lambda: len(sinks.sinks) == 2)
                assert server.charge_point_ids() == ["CP1"]
                assert server.connection("CP1") is sinks.sinks[1].conn
                await until(lambda: sinks.sinks[0].closed.is_set())
                assert not sinks.sinks[1].closed.is_set()
                await new.send("still alive")
                await until(lambda: sinks.sinks[1].frames == ["still alive"])


async def test_charge_point_ids_are_sorted() -> None:
    sinks = Sinks()
    async with make(sinks) as server:
        async with (
            connect(url(server, "B"), subprotocols=sp("ocpp1.6")),
            connect(url(server, "A"), subprotocols=sp("ocpp1.6")),
            connect(url(server, "C"), subprotocols=sp("ocpp1.6")),
        ):
            await until(lambda: len(server.charge_point_ids()) == 3)
            assert server.charge_point_ids() == ["A", "B", "C"]


async def test_binary_frames_are_rejected_with_1003() -> None:
    sinks = Sinks()
    async with make(sinks) as server:
        async with connect(url(server), subprotocols=sp("ocpp1.6")) as ws:
            await ws.send(b"\x00\x01")
            with pytest.raises(ConnectionClosed):
                await ws.recv()
            assert ws.protocol.close_code == 1003
        assert sinks.sinks[0].frames == []


async def test_oversized_message_closes_with_1009() -> None:
    sinks = Sinks()
    async with make(sinks, max_message_size=100) as server:
        async with connect(url(server), subprotocols=sp("ocpp1.6")) as ws:
            await ws.send("x" * 101)
            with pytest.raises(ConnectionClosed):
                await ws.recv()
            assert ws.protocol.close_code == 1009


async def test_default_max_message_size_is_1_mib() -> None:
    sinks = Sinks(echo=True)
    async with make(sinks) as server:
        async with connect(url(server), subprotocols=sp("ocpp1.6"), max_size=None) as ws:
            await ws.send("x" * (1024 * 1024))
            assert len(await ws.recv()) == 1024 * 1024
            await ws.send("x" * (1024 * 1024 + 1))
            with pytest.raises(ConnectionClosed):
                await ws.recv()
            assert ws.protocol.close_code == 1009


async def test_on_connect_failure_closes_with_1011(caplog: pytest.LogCaptureFixture) -> None:
    async def boom(conn: Any) -> Any:
        raise RuntimeError("nope")

    server = Server(boom, port=0)
    with caplog.at_level(logging.ERROR, logger="ocpp_sdk.transport.server"):
        async with server:
            async with connect(url(server), subprotocols=sp("ocpp1.6")) as ws:
                with pytest.raises(ConnectionClosed):
                    await ws.recv()
                assert ws.protocol.close_code == 1011
            await until(lambda: server.charge_point_ids() == [])
    assert "connection of CP1 failed" in caplog.text


async def test_shutdown_closes_connections_with_1001() -> None:
    sinks = Sinks()
    server = make(sinks)
    await server.start()
    async with connect(url(server), subprotocols=sp("ocpp1.6")) as ws:
        await until(lambda: len(server.charge_point_ids()) == 1)
        await server.shutdown()
        with pytest.raises(ConnectionClosed):
            await ws.recv()
        assert ws.protocol.close_code == 1001
    assert sinks.sinks[0].closed.is_set()
    assert server.charge_point_ids() == []
    await server.shutdown()  # idempotent


async def test_shutdown_without_start_is_a_noop() -> None:
    await make(Sinks()).shutdown()


async def test_shutdown_timeout_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    sinks = Sinks()

    async def slow_disconnect(conn: Any) -> None:
        await asyncio.sleep(30)

    server = Server(sinks.on_connect, on_disconnect=slow_disconnect, port=0)
    await server.start()
    async with connect(url(server), subprotocols=sp("ocpp1.6")) as ws:
        await until(lambda: len(server.charge_point_ids()) == 1)
        with caplog.at_level(logging.WARNING, logger="ocpp_sdk.transport.server"):
            await server.shutdown(timeout=0.1)
        with pytest.raises(ConnectionClosed):
            await ws.recv()
    assert "shutdown timed out" in caplog.text


async def test_handshake_that_completes_after_shutdown_started_is_closed_with_1001() -> None:
    sinks = Sinks()
    gate = asyncio.Event()
    entered = asyncio.Event()

    async def known(cp: str) -> bool:
        if cp == "LATE":
            entered.set()
            await gate.wait()
        return True

    async def slow_disconnect(conn: Any) -> None:
        await asyncio.sleep(0.5)  # keeps shutdown busy while the late handshake finishes

    server = Server(sinks.on_connect, on_disconnect=slow_disconnect, port=0, known_id=known)
    await server.start()
    port = server.port

    async def late_client() -> int | None:
        async with connect(f"ws://127.0.0.1:{port}/ocpp/LATE", subprotocols=sp("ocpp1.6")) as ws:
            with pytest.raises(ConnectionClosed):
                await ws.recv()
            return ws.protocol.close_code

    async with connect(url(server), subprotocols=sp("ocpp1.6")):
        await until(lambda: server.charge_point_ids() == ["CP1"])
        client = asyncio.create_task(late_client())
        await asyncio.wait_for(entered.wait(), 3)
        stopping = asyncio.create_task(server.shutdown(5))
        await asyncio.sleep(0.05)
        gate.set()
        assert await asyncio.wait_for(client, 5) == 1001
        await stopping
    assert len(sinks.sinks) == 1  # the late connection never registered


async def test_port_requires_start() -> None:
    server = make(Sinks())
    with pytest.raises(AssertionError):
        _ = server.port


async def test_concurrent_connections() -> None:
    sinks = Sinks(echo=True)
    async with make(sinks) as server:

        async def one(i: int) -> None:
            async with connect(url(server, f"CP{i:03d}"), subprotocols=sp("ocpp2.0.1")) as ws:
                for n in range(5):
                    await ws.send(f"{i}-{n}")
                    assert await ws.recv() == f"{i}-{n}"

        await asyncio.gather(*(one(i) for i in range(25)))
        await until(lambda: server.charge_point_ids() == [])
        assert len(sinks.sinks) == 25


async def test_unresponsive_peer_is_dropped_by_the_keepalive() -> None:
    sinks = Sinks()
    async with make(sinks, ping_interval=0.05, ping_timeout=0.05, close_timeout=0.1) as server:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        key = base64.b64encode(os.urandom(16)).decode()
        writer.write(
            (
                "GET /ocpp/CP1 HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                "Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Protocol: ocpp1.6\r\n\r\n"
            ).encode()
        )
        await writer.drain()
        assert b"101" in await reader.readuntil(b"\r\n\r\n")
        await until(lambda: len(sinks.sinks) == 1)
        # never answer the server's pings: it must give up and close the connection
        await until(lambda: sinks.sinks[0].closed.is_set(), timeout=3)
        writer.close()
