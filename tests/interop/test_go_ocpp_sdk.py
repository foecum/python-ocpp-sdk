"""Interop with go-ocpp-sdk v1.1.0: its example station and Central System speak OCPP 1.6 and
2.0.1 to ours over a real WebSocket.

Needs the ``go`` tool and network access (or a warm module cache); skipped otherwise.
"""

import asyncio
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GO_VERSION = "v1.1.0"
MODULE = "github.com/foecum/go-ocpp-sdk/examples"
BINARIES = {"v16": ("csms", "chargepoint"), "v201": ("csms", "chargingstation")}

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def go_examples(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """A directory with ``v16/`` and ``v201/`` holding the built Go examples."""
    if shutil.which("go") is None:
        pytest.skip("the go tool is not installed")
    root = tmp_path_factory.mktemp("go-bin")
    for version, names in BINARIES.items():
        env = {**os.environ, "GOBIN": str(root / version)}
        for name in names:
            built = subprocess.run(
                ["go", "install", f"{MODULE}/{version}/{name}@{GO_VERSION}"],
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if built.returncode != 0:
                pytest.skip(f"cannot build go-ocpp-sdk {GO_VERSION}: {built.stderr.strip()[-300:]}")
    yield root


async def free_port() -> int:
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port: int = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    return port


async def spawn(*args: str | Path) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *map(str, args),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=ROOT,
    )


async def read_until(process: asyncio.subprocess.Process, needle: bytes) -> bytes:
    assert process.stdout is not None
    seen = b""
    async with asyncio.timeout(30):
        while needle not in seen:
            line = await process.stdout.readline()
            if not line:
                break
            seen += line
    assert needle in seen, seen.decode()
    return seen


async def stop(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        process.terminate()
    await process.wait()


async def test_go_charge_point_against_our_csms(go_examples: Path) -> None:
    port = await free_port()
    csms = await spawn(sys.executable, "-u", ROOT / "examples/v16/csms.py", "--port", str(port))
    try:
        await read_until(csms, b"listening on")
        station = await spawn(
            go_examples / "v16/chargepoint",
            "-url", f"ws://127.0.0.1:{port}/ocpp",
            "-id", "GO-1",
            "-sessions", "1",
            "-session-length", "2s",
            "-meter-every", "1s",
            "-idle", "1s",
        )  # fmt: skip
        out, _ = await asyncio.wait_for(station.communicate(), timeout=60)
        assert station.returncode == 0, out.decode()
        seen = await read_until(csms, b"transaction 1 stopped")
        assert b"GO-1: boot from" in seen and b"GO-1: transaction 1 started" in seen
        assert b"configuration keys" in seen  # our CSMS called the Go station back
    finally:
        await stop(csms)


async def test_our_charge_point_against_the_go_csms(go_examples: Path) -> None:
    port = await free_port()
    csms = await spawn(go_examples / "v16/csms", "-addr", f"127.0.0.1:{port}")
    try:
        await asyncio.sleep(1)
        station = await spawn(
            sys.executable,
            "-u",
            ROOT / "examples/v16/charge_point.py",
            "--url",
            f"ws://127.0.0.1:{port}/ocpp/PY-1",
        )
        out, _ = await asyncio.wait_for(station.communicate(), timeout=60)
        text = out.decode()
        assert station.returncode == 0, text
        assert "boot: Accepted" in text and "transaction stopped" in text
        assert b"PY-1" in await read_until(csms, b"PY-1")
    finally:
        await stop(csms)


async def test_go_charging_station_against_our_csms(go_examples: Path) -> None:
    port = await free_port()
    csms = await spawn(sys.executable, "-u", ROOT / "examples/v201/csms.py", "--port", str(port))
    try:
        await read_until(csms, b"listening on")
        station = await spawn(
            go_examples / "v201/chargingstation",
            "-url", f"ws://127.0.0.1:{port}/ocpp",
            "-id", "GO-2",
            "-sessions", "1",
            "-session-length", "2s",
            "-meter-every", "1s",
            "-idle", "1s",
        )  # fmt: skip
        out, _ = await asyncio.wait_for(station.communicate(), timeout=60)
        assert station.returncode == 0, out.decode()
        seen = await read_until(csms, b"Ended")
        assert b"GO-2: boot from" in seen and b"Started" in seen
        assert b"HeartbeatInterval" in seen  # our CSMS read a variable from the Go station
    finally:
        await stop(csms)


async def test_our_charging_station_against_the_go_csms(go_examples: Path) -> None:
    port = await free_port()
    csms = await spawn(go_examples / "v201/csms", "-addr", f"127.0.0.1:{port}")
    try:
        await asyncio.sleep(1)
        station = await spawn(
            sys.executable,
            "-u",
            ROOT / "examples/v201/charging_station.py",
            "--url",
            f"ws://127.0.0.1:{port}/ocpp/PY-2",
        )
        out, _ = await asyncio.wait_for(station.communicate(), timeout=60)
        text = out.decode()
        assert station.returncode == 0, text
        assert "boot: Accepted" in text and "transaction ended" in text
        assert b"PY-2" in await read_until(csms, b"PY-2")
    finally:
        await stop(csms)
