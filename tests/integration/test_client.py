import asyncio
import logging
import socket
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve

from ocpp_sdk.errors import NotConnectedError
from ocpp_sdk.transport import Client, Reconnect, Server
from ocpp_sdk.transport.connection import Connection
from ocpp_sdk.versions import Version
from tests.integration.helpers import Sinks, until


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


class Sleeps:
    """Fake sleep: records the requested delays and yields briefly instead of waiting."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        await asyncio.sleep(0.005)


def server_for(sinks: Sinks, **kwargs: Any) -> Server:
    return Server(sinks.on_connect, on_disconnect=sinks.on_disconnect, port=0, **kwargs)


def test_reconnect_delay_follows_the_spec_backoff() -> None:
    r = Reconnect(wait_minimum=10, random_range=10, repeat_times=2)
    assert [r.delay(n, lambda: 0.0) for n in range(5)] == [10, 20, 40, 40, 40]
    assert [r.delay(n, lambda: 1.0) for n in range(5)] == [20, 40, 80, 80, 80]
    assert Reconnect().wait_minimum == 1.0
    assert Reconnect().random_range == 2.0
    assert Reconnect().repeat_times == 6
    assert 1.0 <= Reconnect().delay(0) <= 3.0


def test_url_needs_an_id() -> None:
    sinks = Sinks()
    with pytest.raises(ValueError, match="charge point ID"):
        Client("ws://127.0.0.1:1/ocpp/", sinks.on_connect)


async def test_connect_and_echo() -> None:
    server_sinks, client_sinks = Sinks(echo=True), Sinks()
    async with server_for(server_sinks) as server:
        client = Client(
            f"ws://127.0.0.1:{server.port}/ocpp/CP1",
            client_sinks.on_connect,
            versions=(Version.OCPP16, Version.OCPP201),
        )
        async with client:
            conn = client.connection
            assert conn is not None
            assert (conn.charge_point_id, conn.version) == ("CP1", Version.OCPP201)
            await conn.send("ping")
            await until(lambda: client_sinks.sinks[0].frames == ["ping"])
        assert client.connection is None
        assert client_sinks.sinks[0].closed.is_set()
        with pytest.raises(NotConnectedError):
            await client.wait_connected()


async def test_client_offers_its_versions_in_order() -> None:
    sinks, client_sinks = Sinks(), Sinks()
    async with server_for(sinks, versions=(Version.OCPP16,)) as server:
        async with Client(
            f"ws://127.0.0.1:{server.port}/CP1",
            client_sinks.on_connect,
            versions=(Version.OCPP21, Version.OCPP16),
        ) as client:
            assert client.connection is not None
            assert client.connection.version is Version.OCPP16


async def test_no_reconnect_failure_raises() -> None:
    client = Client(
        f"ws://127.0.0.1:{free_port()}/CP1", Sinks().on_connect, reconnect=None, open_timeout=2
    )
    with pytest.raises(NotConnectedError):
        async with client:
            pass  # pragma: no cover - never entered


async def test_wait_connected_timeout() -> None:
    sleeps = Sleeps()
    client = Client(
        f"ws://127.0.0.1:{free_port()}/CP1",
        Sinks().on_connect,
        reconnect=Reconnect(1, 0, 3),
        sleep=sleeps,
        rng=lambda: 0.0,
    )
    client.start()
    client.start()  # idempotent
    with pytest.raises(TimeoutError):
        await client.wait_connected(timeout=0.1)
    await client.close()


async def test_backoff_after_failed_attempts_doubles_then_stays() -> None:
    sleeps = Sleeps()
    client = Client(
        f"ws://127.0.0.1:{free_port()}/CP1",
        Sinks().on_connect,
        reconnect=Reconnect(wait_minimum=1, random_range=0, repeat_times=3),
        sleep=sleeps,
        rng=lambda: 0.0,
    )
    client.start()
    await until(lambda: len(sleeps.delays) >= 7)
    await client.close()
    assert sleeps.delays[:7] == [1, 2, 4, 8, 8, 8, 8]


async def test_waits_after_a_lost_connection_and_reconnects() -> None:
    sinks, client_sinks = Sinks(), Sinks()
    sleeps = Sleeps()
    async with server_for(sinks) as server:
        client = Client(
            f"ws://127.0.0.1:{server.port}/CP1",
            client_sinks.on_connect,
            reconnect=Reconnect(wait_minimum=1, random_range=0, repeat_times=3),
            sleep=sleeps,
            rng=lambda: 0.0,
        )
        async with client:
            await until(lambda: server.connection("CP1") is not None)
            first = server.connection("CP1")
            assert first is not None
            await first.close(1011, "boom")
            await until(lambda: len(client_sinks.sinks) == 2)
            await client.wait_connected(2)
            assert sleeps.delays == [1]  # the wait applies after a lost connection too
            assert client_sinks.sinks[0].closed.is_set()


async def test_a_failing_on_connect_is_retried(caplog: pytest.LogCaptureFixture) -> None:
    sinks, client_sinks = Sinks(), Sinks()
    sleeps = Sleeps()
    calls = 0

    async def on_connect(conn: Connection) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("cannot build the endpoint")
        return await client_sinks.on_connect(conn)

    async with server_for(sinks) as server:
        client = Client(
            f"ws://127.0.0.1:{server.port}/CP1",
            on_connect,
            reconnect=Reconnect(wait_minimum=1, random_range=0, repeat_times=3),
            sleep=sleeps,
            rng=lambda: 0.0,
        )
        with caplog.at_level(logging.ERROR, "ocpp_sdk.transport.client"):
            async with client:
                assert calls == 2 and sleeps.delays == [1]
        assert "connection failed" in caplog.text


async def test_backoff_resets_after_a_successful_connection() -> None:
    sinks, client_sinks = Sinks(), Sinks()
    sleeps = Sleeps()
    server = server_for(sinks)
    await server.start()
    port = server.port
    client = Client(
        f"ws://127.0.0.1:{port}/CP1",
        client_sinks.on_connect,
        reconnect=Reconnect(wait_minimum=1, random_range=0, repeat_times=5),
        sleep=sleeps,
        rng=lambda: 0.0,
    )

    async def drop_current_and_wait_for_new(old: Connection | None) -> Connection:
        await until(lambda: server.connection("CP1") not in (None, old))
        current = server.connection("CP1")
        assert current is not None
        await current.close(1011)
        await until(lambda: server.connection("CP1") not in (None, current))
        return current

    async with client:
        first = await drop_current_and_wait_for_new(None)
        await drop_current_and_wait_for_new(first)
    await server.shutdown()
    assert sleeps.delays == [1, 1]


async def test_subprotocol_mismatch_counts_as_a_failed_attempt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sinks, client_sinks = Sinks(), Sinks()
    sleeps = Sleeps()
    async with server_for(sinks, versions=(Version.OCPP16,)) as server:
        client = Client(
            f"ws://127.0.0.1:{server.port}/CP1",
            client_sinks.on_connect,
            versions=(Version.OCPP201,),
            reconnect=Reconnect(wait_minimum=1, random_range=0, repeat_times=2),
            sleep=sleeps,
            rng=lambda: 0.0,
        )
        with caplog.at_level(logging.WARNING, logger="ocpp_sdk.transport.client"):
            client.start()
            await until(lambda: len(sleeps.delays) >= 4)
        await client.close()
        assert sleeps.delays[:4] == [1, 2, 4, 4]
        assert client_sinks.sinks == []
        assert "no OCPP subprotocol" in caplog.text


async def test_no_reconnect_after_mismatch_gives_up() -> None:
    sinks = Sinks()
    async with server_for(sinks, versions=(Version.OCPP16,)) as server:
        client = Client(
            f"ws://127.0.0.1:{server.port}/CP1",
            sinks.on_connect,
            versions=(Version.OCPP201,),
            reconnect=None,
        )
        with pytest.raises(NotConnectedError, match="subprotocol"):
            async with client:
                pass  # pragma: no cover


async def test_basic_auth_password() -> None:
    sinks, client_sinks = Sinks(), Sinks()
    sleeps = Sleeps()

    def check(cp: str, password: str) -> bool:
        return password == "s3cret"

    async with server_for(sinks, authenticate=check) as server:
        url = f"ws://127.0.0.1:{server.port}/ocpp/CP1"
        async with Client(url, client_sinks.on_connect, password="s3cret"):
            await until(lambda: server.charge_point_ids() == ["CP1"])
        bad = Client(
            url,
            client_sinks.on_connect,
            password="nope",
            reconnect=Reconnect(1, 0, 1),
            sleep=sleeps,
        )
        bad.start()
        await until(lambda: len(sleeps.delays) >= 2)
        await bad.close()
        assert bad.connection is None


async def test_binary_frame_from_server_closes_the_client_session() -> None:
    client_sinks = Sinks()

    async def handler(ws: ServerConnection) -> None:
        await ws.send(b"\x01")
        await ws.wait_closed()

    async with serve(handler, "127.0.0.1", 0, subprotocols=["ocpp2.0.1"]) as raw:  # type: ignore[list-item]
        port = next(iter(raw.sockets)).getsockname()[1]
        client = Client(f"ws://127.0.0.1:{port}/CP1", client_sinks.on_connect, reconnect=None)
        client.start()
        await until(lambda: client_sinks.sinks != [] and client_sinks.sinks[0].closed.is_set())
        await client.close()
        assert client_sinks.sinks[0].frames == []


async def test_close_while_connected_and_while_waiting() -> None:
    sinks, client_sinks = Sinks(), Sinks()
    async with server_for(sinks) as server:
        client = Client(f"ws://127.0.0.1:{server.port}/CP1", client_sinks.on_connect)
        await client.__aenter__()
        await client.close()
        await until(lambda: server.charge_point_ids() == [])
        await client.close()  # idempotent
    never = Client(f"ws://127.0.0.1:{free_port()}/CP1", sinks.on_connect)
    never.start()
    await asyncio.sleep(0.05)
    await never.close()
    assert never.connection is None


async def test_close_without_start() -> None:
    client = Client("ws://127.0.0.1:1/CP1", Sinks().on_connect)
    await client.close()
    with pytest.raises(NotConnectedError):
        await client.wait_connected()


async def test_on_connect_passes_connection_object() -> None:
    seen: list[Connection] = []
    sinks = Sinks()

    async def on_connect(conn: Connection) -> Any:
        seen.append(conn)
        return await sinks.on_connect(conn)

    async with server_for(Sinks()) as server:
        async with Client(f"ws://127.0.0.1:{server.port}/CP1", on_connect):
            assert seen[0].charge_point_id == "CP1"
