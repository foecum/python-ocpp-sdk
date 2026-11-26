"""A small OCPP 2.0.1 CSMS.

It accepts every station, prints what it receives and, after a station boots, reads one variable
from it with GetVariables.

    uv run python examples/v201/csms.py --port 9000 [--password SECRET]

Stations connect to ``ws://<host>:<port>/<station id>``. With ``--password`` the station must send
it as the HTTP Basic password (security profile 1; use TLS on a real network).
"""

import argparse
import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from ocpp_sdk.v201.authorization import AuthorizeRequest, AuthorizeResponse
from ocpp_sdk.v201.availability import (
    HeartbeatRequest,
    HeartbeatResponse,
    StatusNotificationRequest,
    StatusNotificationResponse,
)
from ocpp_sdk.v201.csms import CSMS, ChargingStation, Config
from ocpp_sdk.v201.csms_handlers import (
    UnimplementedAuthorizationHandler,
    UnimplementedAvailabilityHandler,
    UnimplementedMeterValuesHandler,
    UnimplementedProvisioningHandler,
    UnimplementedTransactionsHandler,
)
from ocpp_sdk.v201.metervalues import MeterValuesRequest, MeterValuesResponse
from ocpp_sdk.v201.provisioning import (
    BootNotificationRequest,
    BootNotificationResponse,
    GetVariablesRequest,
)
from ocpp_sdk.v201.transactions import TransactionEventRequest, TransactionEventResponse
from ocpp_sdk.v201.types import (
    AuthorizationStatus,
    Component,
    GetVariableData,
    IdTokenInfo,
    RegistrationStatus,
    Variable,
)


class Provisioning(UnimplementedProvisioningHandler):
    def on_boot_notification(
        self, charging_station: ChargingStation, request: BootNotificationRequest
    ) -> BootNotificationResponse:
        print(
            f"{charging_station.charge_point_id}: boot from {request.charging_station.vendor_name}"
        )
        return BootNotificationResponse(
            current_time=datetime.now(UTC), interval=60, status=RegistrationStatus.ACCEPTED
        )


class Authorization(UnimplementedAuthorizationHandler):
    def on_authorize(
        self, charging_station: ChargingStation, request: AuthorizeRequest
    ) -> AuthorizeResponse:
        return AuthorizeResponse(id_token_info=IdTokenInfo(status=AuthorizationStatus.ACCEPTED))


class Availability(UnimplementedAvailabilityHandler):
    def on_heartbeat(
        self, charging_station: ChargingStation, request: HeartbeatRequest
    ) -> HeartbeatResponse:
        return HeartbeatResponse(current_time=datetime.now(UTC))

    def on_status_notification(
        self, charging_station: ChargingStation, request: StatusNotificationRequest
    ) -> StatusNotificationResponse:
        station_id = charging_station.charge_point_id
        print(f"{station_id}: connector {request.connector_id} {request.connector_status}")
        return StatusNotificationResponse()


class Transactions(UnimplementedTransactionsHandler):
    def on_transaction_event(
        self, charging_station: ChargingStation, request: TransactionEventRequest
    ) -> TransactionEventResponse:
        info = request.transaction_info.transaction_id
        print(f"{charging_station.charge_point_id}: transaction {info} {request.event_type}")
        return TransactionEventResponse()


class MeterValues(UnimplementedMeterValuesHandler):
    def on_meter_values(
        self, charging_station: ChargingStation, request: MeterValuesRequest
    ) -> MeterValuesResponse:
        return MeterValuesResponse()


async def read_a_variable(station: ChargingStation) -> None:
    """Call the station back once it is connected."""
    await asyncio.sleep(0.5)
    request = GetVariablesRequest(
        get_variable_data=[
            GetVariableData(
                component=Component(name="OCPPCommCtrlr"),
                variable=Variable(name="HeartbeatInterval"),
            )
        ]
    )
    try:
        answer = await station.get_variables(request)
    except Exception as exc:  # a station may not support it
        print(f"{station.charge_point_id}: GetVariables failed: {exc}")
        return
    value = answer.get_variable_result[0].attribute_value
    print(f"{station.charge_point_id}: HeartbeatInterval = {value}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--password", help="require this HTTP Basic password")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    background: set[asyncio.Task[None]] = set()

    def on_connect(station: ChargingStation) -> None:
        task = asyncio.get_running_loop().create_task(read_a_variable(station))
        background.add(task)
        task.add_done_callback(background.discard)

    def authenticate(charge_point_id: str, password: str) -> bool:
        return bool(password == args.password)

    config = Config(
        provisioning=Provisioning(),
        authorization=Authorization(),
        availability=Availability(),
        transactions=Transactions(),
        meter_values=MeterValues(),
    )
    csms = CSMS(
        config,
        host=args.host,
        port=args.port,
        authenticate=authenticate if args.password else None,
        on_connect=on_connect,
    )
    async with csms:
        print(f"listening on ws://{args.host}:{csms.port}/<station id>")
        await asyncio.Event().wait()  # until interrupted


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
