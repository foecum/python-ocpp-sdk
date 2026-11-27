"""A small run of the load test (the 1,000-station run is manual)."""

import pytest
from examples.loadtest.loadtest import run

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("version", ["16", "201", "21"])
async def test_twenty_stations_for_two_seconds(version: str) -> None:
    result = await run(version, stations=20, seconds=2.0)
    assert result.stations == 20 and result.operations > 200
    assert 0 < result.percentile(0.5) <= result.percentile(0.99) <= max(result.latencies)
    assert "calls/s" in result.summary()
