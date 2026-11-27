"""The 2.1 examples run against each other as separate processes."""

import asyncio
from pathlib import Path

import pytest

from tests.integration.test_v16_examples import free_port, read_until, spawn

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "v21"

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("password", [None, "s3cret"])
async def test_charging_station_example_against_csms_example(password: str | None) -> None:
    port = await free_port()
    extra = ["--password", password] if password else []
    csms = await spawn(str(EXAMPLES / "csms.py"), "--port", str(port), *extra)
    try:
        await read_until(csms, b"listening on")
        station = await spawn(
            str(EXAMPLES / "charging_station.py"), "--url", f"ws://127.0.0.1:{port}/CS-1", *extra
        )
        out, _ = await asyncio.wait_for(station.communicate(), timeout=30)
        assert station.returncode == 0, out.decode()
        text = out.decode()
        assert "boot: Accepted" in text and "periodic event stream sent" in text
        seen = await read_until(csms, b"HeartbeatInterval = 60")
        assert b"CS-1: boot from Example" in seen and b"transaction T-1 Ended" in seen
        assert b"periodic event stream 1: 2 values" in seen  # the SEND reached the CSMS
    finally:
        csms.terminate()
        await csms.wait()
