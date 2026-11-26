"""A small OCPP 1.6 Charge Point.

It boots, reports its connector, authorizes a tag, runs one short transaction with meter values,
then disconnects (unless ``--stay``). While connected it answers GetConfiguration and Reset.

    uv run python examples/v16/charge_point.py --url ws://127.0.0.1:9000/CP-1 [--password SECRET]

The URL ends with this station's ID. ``--password`` is the HTTP Basic password (security profile 1).
"""

import argparse
import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from ocpp_sdk.v16.charge_point import ChargePoint, Config
from ocpp_sdk.v16.charge_point_handlers import UnimplementedCoreHandler
from ocpp_sdk.v16.core import (
    AuthorizeRequest,
    BootNotificationRequest,
    GetConfigurationConfirmation,
    GetConfigurationRequest,
    HeartbeatRequest,
    MeterValuesRequest,
    ResetConfirmation,
    ResetRequest,
    StartTransactionRequest,
    StatusNotificationRequest,
    StopTransactionRequest,
)
from ocpp_sdk.v16.types import (
    AuthorizationStatus,
    ChargePointErrorCode,
    ChargePointStatus,
    KeyValue,
    RegistrationStatus,
    ResetStatus,
)


class Core(UnimplementedCoreHandler):
    """Handlers for the Core messages the Central System sends."""

    def on_get_configuration(
        self, request: GetConfigurationRequest
    ) -> GetConfigurationConfirmation:
        return GetConfigurationConfirmation(
            configuration_key=[
                KeyValue(key="HeartbeatInterval", readonly=False, value="60"),
                KeyValue(key="NumberOfConnectors", readonly=True, value="1"),
            ]
        )

    def on_reset(self, request: ResetRequest) -> ResetConfirmation:
        print(f"reset requested: {request.type}")
        return ResetConfirmation(status=ResetStatus.ACCEPTED)


async def run(cp: ChargePoint) -> None:
    boot = await cp.boot_notification(
        BootNotificationRequest(charge_point_vendor="Example", charge_point_model="CP-1")
    )
    print(f"boot: {boot.status}, heartbeat every {boot.interval}s")
    if boot.status is not RegistrationStatus.ACCEPTED:
        return
    await cp.status_notification(
        StatusNotificationRequest(
            connector_id=1,
            error_code=ChargePointErrorCode.NO_ERROR,
            status=ChargePointStatus.AVAILABLE,
        )
    )
    await cp.heartbeat(HeartbeatRequest())
    auth = await cp.authorize(AuthorizeRequest(id_tag="04A2B3C4"))
    if auth.id_tag_info.status is not AuthorizationStatus.ACCEPTED:
        print("tag refused")
        return
    started = await cp.start_transaction(
        StartTransactionRequest(
            connector_id=1, id_tag="04A2B3C4", meter_start=0, timestamp=datetime.now(UTC)
        )
    )
    print(f"transaction {started.transaction_id}")
    await cp.meter_values(
        MeterValuesRequest.model_validate(
            {
                "connectorId": 1,
                "transactionId": started.transaction_id,
                "meterValue": [
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "sampledValue": [{"value": "1500", "unit": "Wh"}],
                    }
                ],
            }
        )
    )
    await cp.stop_transaction(
        StopTransactionRequest(
            meter_stop=1500, timestamp=datetime.now(UTC), transaction_id=started.transaction_id
        )
    )
    print("transaction stopped")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="ws://127.0.0.1:9000/CP-1")
    parser.add_argument("--password")
    parser.add_argument("--stay", action="store_true", help="stay connected after the transaction")
    parser.add_argument(
        "--linger", type=float, default=1.0, help="seconds to stay so the CSMS can call back"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    async with ChargePoint(args.url, Config(core=Core()), password=args.password) as cp:
        await run(cp)
        if args.stay:
            await asyncio.Event().wait()
        await asyncio.sleep(args.linger)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
