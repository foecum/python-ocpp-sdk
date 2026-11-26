"""The 1.6 examples run against each other as separate processes."""

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "v16"

pytestmark = pytest.mark.slow


async def free_port() -> int:
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port: int = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    return port


async def spawn(*args: str) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=ROOT,
    )


async def read_until(process: asyncio.subprocess.Process, needle: bytes) -> bytes:
    assert process.stdout is not None
    seen = b""
    async with asyncio.timeout(20):
        while needle not in seen:
            line = await process.stdout.readline()
            if not line:
                break
            seen += line
    assert needle in seen, seen.decode()
    return seen


@pytest.mark.parametrize("password", [None, "s3cret"])
async def test_charge_point_example_against_csms_example(password: str | None) -> None:
    port = await free_port()
    extra = ["--password", password] if password else []
    csms = await spawn(str(EXAMPLES / "csms.py"), "--port", str(port), *extra)
    try:
        await read_until(csms, b"listening on")
        station = await spawn(
            str(EXAMPLES / "charge_point.py"), "--url", f"ws://127.0.0.1:{port}/CP-1", *extra
        )
        out, _ = await asyncio.wait_for(station.communicate(), timeout=30)
        assert station.returncode == 0, out.decode()
        text = out.decode()
        assert (
            "boot: Accepted" in text and "transaction 1" in text and "transaction stopped" in text
        )
        seen = await read_until(csms, b"transaction 1 stopped")
        assert b"CP-1: boot from Example" in seen
    finally:
        csms.terminate()
        await csms.wait()


async def test_a_wrong_password_is_refused() -> None:
    port = await free_port()
    csms = await spawn(str(EXAMPLES / "csms.py"), "--port", str(port), "--password", "right")
    try:
        await read_until(csms, b"listening on")
        station = await spawn(
            str(EXAMPLES / "charge_point.py"),
            "--url",
            f"ws://127.0.0.1:{port}/CP-1",
            "--password",
            "wrong",
        )
        # the station keeps retrying with the reconnect back-off; it never boots
        await asyncio.sleep(1.5)
        assert station.returncode is None
        station.terminate()
        out, _ = await station.communicate()
        assert b"boot:" not in out
    finally:
        csms.terminate()
        await csms.wait()
