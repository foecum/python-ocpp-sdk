"""A small OCPP 2.0.1 Charging Station.

It boots, reports its connector, authorizes a token, runs one short transaction (TransactionEvent
Started, Updated with a meter value, Ended), then disconnects (unless ``--stay``). While connected
it answers GetVariables and SetVariables.

    uv run python examples/v201/charging_station.py --url ws://127.0.0.1:9000/CS-1

The URL ends with this station's ID. ``--password SECRET`` sets the HTTP Basic password
(security profile 1).
"""

import argparse
import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

from ocpp_sdk.v201.authorization import AuthorizeRequest
from ocpp_sdk.v201.availability import HeartbeatRequest, StatusNotificationRequest
from ocpp_sdk.v201.charging_station import ChargingStation, Config
from ocpp_sdk.v201.charging_station_handlers import UnimplementedProvisioningHandler
from ocpp_sdk.v201.provisioning import (
    BootNotificationRequest,
    GetVariablesRequest,
    GetVariablesResponse,
    SetVariablesRequest,
    SetVariablesResponse,
)
from ocpp_sdk.v201.transactions import TransactionEventRequest
from ocpp_sdk.v201.types import (
    AuthorizationStatus,
    BootReason,
    ConnectorStatus,
    GetVariableResult,
    GetVariableStatus,
    IdToken,
    IdTokenEnum,
    RegistrationStatus,
    SetVariableResult,
    SetVariableStatus,
)
from ocpp_sdk.v201.types import ChargingStation as StationInfo


class Provisioning(UnimplementedProvisioningHandler):
    """Answers GetVariables and SetVariables from a tiny in-memory device model."""

    def __init__(self) -> None:
        self.values = {("OCPPCommCtrlr", "HeartbeatInterval"): "60"}

    def on_get_variables(self, request: GetVariablesRequest) -> GetVariablesResponse:
        results = []
        for item in request.get_variable_data:
            value = self.values.get((item.component.name, item.variable.name))
            results.append(
                GetVariableResult(
                    attribute_status=(
                        GetVariableStatus.ACCEPTED
                        if value is not None
                        else GetVariableStatus.UNKNOWN_VARIABLE
                    ),
                    attribute_value=value,
                    component=item.component,
                    variable=item.variable,
                )
            )
        return GetVariablesResponse(get_variable_result=results)

    def on_set_variables(self, request: SetVariablesRequest) -> SetVariablesResponse:
        results = []
        for item in request.set_variable_data:
            self.values[(item.component.name, item.variable.name)] = item.attribute_value
            results.append(
                SetVariableResult(
                    attribute_status=SetVariableStatus.ACCEPTED,
                    component=item.component,
                    variable=item.variable,
                )
            )
        return SetVariablesResponse(set_variable_result=results)


def event(kind: str, seq: int, reason: str, **extra: Any) -> TransactionEventRequest:
    """A TransactionEvent for transaction ``T-1``."""
    payload: dict[str, Any] = {
        "eventType": kind,
        "timestamp": datetime.now(UTC).isoformat(),
        "triggerReason": reason,
        "seqNo": seq,
        "transactionInfo": {"transactionId": "T-1"},
        **extra,
    }
    return TransactionEventRequest.model_validate(payload)


async def run(station: ChargingStation) -> None:
    boot = await station.boot_notification(
        BootNotificationRequest(
            charging_station=StationInfo(model="CS-1", vendor_name="Example"),
            reason=BootReason.POWER_UP,
        )
    )
    print(f"boot: {boot.status}, heartbeat every {boot.interval}s")
    if boot.status is not RegistrationStatus.ACCEPTED:
        return
    await station.status_notification(
        StatusNotificationRequest(
            timestamp=datetime.now(UTC),
            connector_status=ConnectorStatus.AVAILABLE,
            evse_id=1,
            connector_id=1,
        )
    )
    await station.heartbeat(HeartbeatRequest())
    token = IdToken(id_token="04A2B3C4", type=IdTokenEnum.ISO14443)
    auth = await station.authorize(AuthorizeRequest(id_token=token))
    if auth.id_token_info.status is not AuthorizationStatus.ACCEPTED:
        print("token refused")
        return
    await station.transaction_event(
        event("Started", 0, "Authorized", idToken=token.model_dump(by_alias=True))
    )
    meter = {
        "meterValue": [
            {"timestamp": datetime.now(UTC).isoformat(), "sampledValue": [{"value": 1500}]}
        ]
    }
    await station.transaction_event(event("Updated", 1, "MeterValuePeriodic", **meter))
    await station.transaction_event(event("Ended", 2, "EVDeparted"))
    print("transaction ended")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="ws://127.0.0.1:9000/CS-1")
    parser.add_argument("--password")
    parser.add_argument("--stay", action="store_true", help="stay connected after the transaction")
    parser.add_argument(
        "--linger", type=float, default=1.0, help="seconds to stay so the CSMS can call back"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    config = Config(provisioning=Provisioning())
    async with ChargingStation(args.url, config, password=args.password) as station:
        await run(station)
        if args.stay:
            await asyncio.Event().wait()
        await asyncio.sleep(args.linger)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
