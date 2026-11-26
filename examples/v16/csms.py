"""A small OCPP 1.6 Central System.

It accepts every station, hands out transaction ids, prints what it receives and, after a
station boots, asks it for its configuration.

    uv run python examples/v16/csms.py --port 9000 [--password SECRET]

Stations connect to ``ws://<host>:<port>/<charge point id>``. With ``--password`` the station must
send it as the HTTP Basic password (security profile 1; use TLS on a real network).
"""

import argparse
import asyncio
import contextlib
import itertools
import logging
from datetime import UTC, datetime

from ocpp_sdk.v16.core import (
    AuthorizeConfirmation,
    AuthorizeRequest,
    BootNotificationConfirmation,
    BootNotificationRequest,
    GetConfigurationRequest,
    HeartbeatConfirmation,
    HeartbeatRequest,
    MeterValuesConfirmation,
    MeterValuesRequest,
    StartTransactionConfirmation,
    StartTransactionRequest,
    StatusNotificationConfirmation,
    StatusNotificationRequest,
    StopTransactionConfirmation,
    StopTransactionRequest,
)
from ocpp_sdk.v16.csms import CSMS, ChargePoint, Config
from ocpp_sdk.v16.csms_handlers import UnimplementedCoreHandler
from ocpp_sdk.v16.types import AuthorizationStatus, IdTagInfo, RegistrationStatus

ACCEPTED = IdTagInfo(status=AuthorizationStatus.ACCEPTED)


class Core(UnimplementedCoreHandler):
    """Handlers for the Core messages a station sends."""

    def __init__(self) -> None:
        self._transaction_ids = itertools.count(1)

    async def on_boot_notification(
        self, charge_point: ChargePoint, request: BootNotificationRequest
    ) -> BootNotificationConfirmation:
        print(f"{charge_point.charge_point_id}: boot from {request.charge_point_vendor}")
        return BootNotificationConfirmation(
            status=RegistrationStatus.ACCEPTED, current_time=datetime.now(UTC), interval=60
        )

    def on_heartbeat(
        self, charge_point: ChargePoint, request: HeartbeatRequest
    ) -> HeartbeatConfirmation:
        return HeartbeatConfirmation(current_time=datetime.now(UTC))

    def on_status_notification(
        self, charge_point: ChargePoint, request: StatusNotificationRequest
    ) -> StatusNotificationConfirmation:
        print(f"{charge_point.charge_point_id}: connector {request.connector_id} {request.status}")
        return StatusNotificationConfirmation()

    def on_authorize(
        self, charge_point: ChargePoint, request: AuthorizeRequest
    ) -> AuthorizeConfirmation:
        return AuthorizeConfirmation(id_tag_info=ACCEPTED)

    def on_start_transaction(
        self, charge_point: ChargePoint, request: StartTransactionRequest
    ) -> StartTransactionConfirmation:
        transaction_id = next(self._transaction_ids)
        print(f"{charge_point.charge_point_id}: transaction {transaction_id} started")
        return StartTransactionConfirmation(id_tag_info=ACCEPTED, transaction_id=transaction_id)

    def on_meter_values(
        self, charge_point: ChargePoint, request: MeterValuesRequest
    ) -> MeterValuesConfirmation:
        return MeterValuesConfirmation()

    def on_stop_transaction(
        self, charge_point: ChargePoint, request: StopTransactionRequest
    ) -> StopTransactionConfirmation:
        print(f"{charge_point.charge_point_id}: transaction {request.transaction_id} stopped")
        return StopTransactionConfirmation()


async def ask_for_configuration(station: ChargePoint) -> None:
    """Call the station back once it is connected."""
    await asyncio.sleep(0.5)
    try:
        answer = await station.get_configuration(GetConfigurationRequest())
    except Exception as exc:  # a station may not support it
        print(f"{station.charge_point_id}: GetConfiguration failed: {exc}")
        return
    keys = [k.key for k in answer.configuration_key or []]
    print(f"{station.charge_point_id}: configuration keys {keys}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--password", help="require this HTTP Basic password")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    background: set[asyncio.Task[None]] = set()

    def on_connect(station: ChargePoint) -> None:
        task = asyncio.get_running_loop().create_task(ask_for_configuration(station))
        background.add(task)
        task.add_done_callback(background.discard)

    def authenticate(charge_point_id: str, password: str) -> bool:
        return bool(password == args.password)

    csms = CSMS(
        Config(core=Core()),
        host=args.host,
        port=args.port,
        authenticate=authenticate if args.password else None,
        on_connect=on_connect,
    )
    async with csms:
        print(f"listening on ws://{args.host}:{csms.port}/<charge point id>")
        await asyncio.Event().wait()  # until interrupted


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
