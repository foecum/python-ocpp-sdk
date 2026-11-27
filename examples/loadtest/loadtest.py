"""Load test: an in-process CSMS and N stations over loopback WebSockets.

Every station boots, then sends Heartbeat and MeterValues (1.6) or TransactionEvent (2.0.1)
one after the other for the given time. Prints operations per second and latency percentiles.

    uv run python examples/loadtest/loadtest.py --version 16 --stations 20 --seconds 10
    uv run python examples/loadtest/loadtest.py --version 201 --stations 1000 --seconds 30
    uv run python examples/loadtest/loadtest.py --version 21 --stations 20 --seconds 10

Loopback numbers say how much work the SDK does per message on this machine, not what a real
network or station fleet would do. For 1,000 stations raise the open-file limit (``ulimit -n``).
"""

import argparse
import asyncio
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ocpp_sdk.v16 import charge_point as cp16
from ocpp_sdk.v16 import csms as csms16
from ocpp_sdk.v16.charge_point import ChargePoint
from ocpp_sdk.v16.core import (
    BootNotificationConfirmation,
    BootNotificationRequest,
    HeartbeatConfirmation,
    HeartbeatRequest,
    MeterValuesConfirmation,
    MeterValuesRequest,
)
from ocpp_sdk.v16.csms import CSMS
from ocpp_sdk.v16.csms_handlers import UnimplementedCoreHandler
from ocpp_sdk.v16.types import RegistrationStatus
from ocpp_sdk.v21 import csms as csms21
from ocpp_sdk.v21.availability import HeartbeatRequest as Heartbeat21
from ocpp_sdk.v21.availability import HeartbeatResponse as HeartbeatResponse21
from ocpp_sdk.v21.charging_station import ChargingStation as ChargingStation21
from ocpp_sdk.v21.csms import CSMS as CSMS21
from ocpp_sdk.v21.csms_handlers import (
    UnimplementedAvailabilityHandler as UnimplementedAvailabilityHandler21,
)
from ocpp_sdk.v21.csms_handlers import (
    UnimplementedProvisioningHandler as UnimplementedProvisioningHandler21,
)
from ocpp_sdk.v21.csms_handlers import (
    UnimplementedTransactionsHandler as UnimplementedTransactionsHandler21,
)
from ocpp_sdk.v21.provisioning import BootNotificationRequest as Boot21
from ocpp_sdk.v21.provisioning import BootNotificationResponse as BootResponse21
from ocpp_sdk.v21.transactions import TransactionEventRequest as TransactionEventRequest21
from ocpp_sdk.v21.transactions import TransactionEventResponse as TransactionEventResponse21
from ocpp_sdk.v21.types import BootReason as BootReason21
from ocpp_sdk.v21.types import ChargingStation as StationInfo21
from ocpp_sdk.v21.types import RegistrationStatus as Registration21
from ocpp_sdk.v201 import csms as csms201
from ocpp_sdk.v201.availability import HeartbeatRequest as Heartbeat201
from ocpp_sdk.v201.availability import HeartbeatResponse
from ocpp_sdk.v201.charging_station import ChargingStation
from ocpp_sdk.v201.csms import CSMS as CSMS201
from ocpp_sdk.v201.csms_handlers import (
    UnimplementedAvailabilityHandler,
    UnimplementedProvisioningHandler,
    UnimplementedTransactionsHandler,
)
from ocpp_sdk.v201.provisioning import BootNotificationRequest as Boot201
from ocpp_sdk.v201.provisioning import BootNotificationResponse as BootResponse201
from ocpp_sdk.v201.transactions import TransactionEventRequest, TransactionEventResponse
from ocpp_sdk.v201.types import BootReason
from ocpp_sdk.v201.types import ChargingStation as StationInfo
from ocpp_sdk.v201.types import RegistrationStatus as Registration201

NOW = "2025-03-14T09:26:53Z"


@dataclass
class Result:
    """What one run measured."""

    version: str
    stations: int
    seconds: float
    latencies: list[float]  # seconds, one per completed call

    @property
    def operations(self) -> int:
        return len(self.latencies)

    @property
    def per_second(self) -> float:
        return self.operations / self.seconds

    def percentile(self, p: float) -> float:
        ordered = sorted(self.latencies)
        return ordered[min(len(ordered) - 1, int(len(ordered) * p))]

    def summary(self) -> str:
        ms = 1000
        return (
            f"OCPP {self.version}: {self.stations} stations, {self.operations} calls in "
            f"{self.seconds:.1f}s = {self.per_second:,.0f} calls/s; latency ms: "
            f"mean {statistics.fmean(self.latencies) * ms:.2f}, "
            f"p50 {self.percentile(0.5) * ms:.2f}, p95 {self.percentile(0.95) * ms:.2f}, "
            f"p99 {self.percentile(0.99) * ms:.2f}, max {max(self.latencies) * ms:.2f}"
        )


# ------------------------------------------------------------------ OCPP 1.6


class Core16(UnimplementedCoreHandler):
    def on_boot_notification(self, charge_point: Any, request: Any) -> BootNotificationConfirmation:
        return BootNotificationConfirmation(
            status=RegistrationStatus.ACCEPTED, current_time=datetime.now(UTC), interval=300
        )

    def on_heartbeat(self, charge_point: Any, request: Any) -> HeartbeatConfirmation:
        return HeartbeatConfirmation(current_time=datetime.now(UTC))

    def on_meter_values(self, charge_point: Any, request: Any) -> MeterValuesConfirmation:
        return MeterValuesConfirmation()


async def run16(stations: int, seconds: float) -> Result:
    server = CSMS(csms16.Config(core=Core16()), port=0, ping_interval=None)
    await server.start()
    meter = MeterValuesRequest.model_validate(
        {
            "connectorId": 1,
            "meterValue": [{"timestamp": NOW, "sampledValue": [{"value": "1500", "unit": "Wh"}]}],
        }
    )
    latencies: list[float] = []

    async def station(index: int, deadline: float) -> None:
        async with ChargePoint(
            f"ws://127.0.0.1:{server.port}/ocpp/LT-{index}",
            cp16.Config(),
            ping_interval=None,
            reconnect=None,
        ) as cp:
            await cp.boot_notification(
                BootNotificationRequest(charge_point_vendor="Load", charge_point_model="T")
            )
            while time.perf_counter() < deadline:
                for call in (cp.heartbeat(HeartbeatRequest()), cp.meter_values(meter)):
                    start = time.perf_counter()
                    await call
                    latencies.append(time.perf_counter() - start)

    try:
        return await _drive("1.6", stations, seconds, station, latencies)
    finally:
        await server.shutdown(timeout=30)


# ------------------------------------------------------------------ OCPP 2.0.1


class Provisioning201(UnimplementedProvisioningHandler):
    def on_boot_notification(self, charging_station: Any, request: Any) -> BootResponse201:
        return BootResponse201(
            current_time=datetime.now(UTC), interval=300, status=Registration201.ACCEPTED
        )


class Availability201(UnimplementedAvailabilityHandler):
    def on_heartbeat(self, charging_station: Any, request: Any) -> HeartbeatResponse:
        return HeartbeatResponse(current_time=datetime.now(UTC))


class Transactions201(UnimplementedTransactionsHandler):
    def on_transaction_event(self, charging_station: Any, request: Any) -> TransactionEventResponse:
        return TransactionEventResponse()


async def run201(stations: int, seconds: float) -> Result:
    config = csms201.Config(
        provisioning=Provisioning201(),
        availability=Availability201(),
        transactions=Transactions201(),
    )
    server = CSMS201(config, port=0, ping_interval=None)
    await server.start()
    event = TransactionEventRequest.model_validate(
        {
            "eventType": "Updated",
            "timestamp": NOW,
            "triggerReason": "MeterValuePeriodic",
            "seqNo": 1,
            "transactionInfo": {"transactionId": "T-1"},
            "meterValue": [{"timestamp": NOW, "sampledValue": [{"value": 1500}]}],
        }
    )
    latencies: list[float] = []

    async def station(index: int, deadline: float) -> None:
        async with ChargingStation(
            f"ws://127.0.0.1:{server.port}/ocpp/LT-{index}", ping_interval=None, reconnect=None
        ) as cs:
            await cs.boot_notification(
                Boot201(
                    charging_station=StationInfo(model="T", vendor_name="Load"),
                    reason=BootReason.POWER_UP,
                )
            )
            while time.perf_counter() < deadline:
                for call in (cs.heartbeat(Heartbeat201()), cs.transaction_event(event)):
                    start = time.perf_counter()
                    await call
                    latencies.append(time.perf_counter() - start)

    try:
        return await _drive("2.0.1", stations, seconds, station, latencies)
    finally:
        await server.shutdown(timeout=30)


# ------------------------------------------------------------------ OCPP 2.1


class Provisioning21(UnimplementedProvisioningHandler21):
    def on_boot_notification(self, charging_station: Any, request: Any) -> BootResponse21:
        return BootResponse21(
            current_time=datetime.now(UTC), interval=300, status=Registration21.ACCEPTED
        )


class Availability21(UnimplementedAvailabilityHandler21):
    def on_heartbeat(self, charging_station: Any, request: Any) -> HeartbeatResponse21:
        return HeartbeatResponse21(current_time=datetime.now(UTC))


class Transactions21(UnimplementedTransactionsHandler21):
    def on_transaction_event(
        self, charging_station: Any, request: Any
    ) -> TransactionEventResponse21:
        return TransactionEventResponse21()


async def run21(stations: int, seconds: float) -> Result:
    config = csms21.Config(
        provisioning=Provisioning21(),
        availability=Availability21(),
        transactions=Transactions21(),
    )
    server = CSMS21(config, port=0, ping_interval=None)
    await server.start()
    event = TransactionEventRequest21.model_validate(
        {
            "eventType": "Updated",
            "timestamp": NOW,
            "triggerReason": "MeterValuePeriodic",
            "seqNo": 1,
            "transactionInfo": {"transactionId": "T-1"},
            "meterValue": [{"timestamp": NOW, "sampledValue": [{"value": 1500}]}],
        }
    )
    latencies: list[float] = []

    async def station(index: int, deadline: float) -> None:
        async with ChargingStation21(
            f"ws://127.0.0.1:{server.port}/ocpp/LT-{index}", ping_interval=None, reconnect=None
        ) as cs:
            await cs.boot_notification(
                Boot21(
                    charging_station=StationInfo21(model="T", vendor_name="Load"),
                    reason=BootReason21.POWER_UP,
                )
            )
            while time.perf_counter() < deadline:
                for call in (cs.heartbeat(Heartbeat21()), cs.transaction_event(event)):
                    start = time.perf_counter()
                    await call
                    latencies.append(time.perf_counter() - start)

    try:
        return await _drive("2.1", stations, seconds, station, latencies)
    finally:
        await server.shutdown(timeout=30)


# ------------------------------------------------------------------ common


async def _drive(
    version: str, stations: int, seconds: float, station: Any, latencies: list[float]
) -> Result:
    started = time.perf_counter()
    deadline = started + seconds
    await asyncio.gather(*(station(i, deadline) for i in range(stations)))
    return Result(version, stations, time.perf_counter() - started, latencies)


async def run(version: str, stations: int, seconds: float) -> Result:
    """Run the load test for ``version`` (``"16"``, ``"201"`` or ``"21"``)."""
    if version == "16":
        return await run16(stations, seconds)
    if version == "201":
        return await run201(stations, seconds)
    if version == "21":
        return await run21(stations, seconds)
    raise ValueError("version must be 16, 201 or 21")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", choices=["16", "201", "21"], default="16")
    parser.add_argument("--stations", type=int, default=20)
    parser.add_argument("--seconds", type=float, default=10.0)
    args = parser.parse_args()
    print(asyncio.run(run(args.version, args.stations, args.seconds)).summary())


if __name__ == "__main__":
    main()
