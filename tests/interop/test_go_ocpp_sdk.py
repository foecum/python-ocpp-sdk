"""Interop with go-ocpp-sdk v1.1.0: its example station and Central System speak OCPP 1.6
to ours over a real WebSocket.

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
EXAMPLES = ROOT / "examples" / "v16"
GO_VERSION = "v1.1.0"
MODULE = "github.com/foecum/go-ocpp-sdk/examples/v16"

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def go_examples(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    if shutil.which("go") is None:
        pytest.skip("the go tool is not installed")
    bin_dir = tmp_path_factory.mktemp("go-bin")
    env = {**os.environ, "GOBIN": str(bin_dir)}
    for name in ("csms", "chargepoint"):
        built = subprocess.run(
            ["go", "install", f"{MODULE}/{name}@{GO_VERSION}"],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if built.returncode != 0:
            pytest.skip(f"cannot build go-ocpp-sdk {GO_VERSION}: {built.stderr.strip()[-300:]}")
    yield bin_dir


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
    csms = await spawn(sys.executable, "-u", EXAMPLES / "csms.py", "--port", str(port))
    try:
        await read_until(csms, b"listening on")
        station = await spawn(
            go_examples / "chargepoint",
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
    csms = await spawn(go_examples / "csms", "-addr", f"127.0.0.1:{port}")
    try:
        await asyncio.sleep(1)
        station = await spawn(
            sys.executable,
            "-u",
            EXAMPLES / "charge_point.py",
            "--url",
            f"ws://127.0.0.1:{port}/ocpp/PY-1",
        )
        out, _ = await asyncio.wait_for(station.communicate(), timeout=60)
        text = out.decode()
        assert station.returncode == 0, text
        assert "boot: Accepted" in text and "transaction stopped" in text
        seen = await read_until(csms, b"PY-1")
        assert b"PY-1" in seen
    finally:
        await stop(csms)
