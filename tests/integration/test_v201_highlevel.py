"""OCPP 2.0.1 ChargingStation and CSMS over a real loopback WebSocket."""

import re
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from ocpp_sdk.errors import CallError, NotConnectedError
from ocpp_sdk.v201 import charging_station as cs_module
from ocpp_sdk.v201 import charging_station_handlers as csh
from ocpp_sdk.v201 import csms as csms_module
from ocpp_sdk.v201 import csms_handlers as ch
from ocpp_sdk.v201 import new_registry
from ocpp_sdk.v201.authorization import AuthorizeRequest, AuthorizeResponse
from ocpp_sdk.v201.availability import HeartbeatRequest
from ocpp_sdk.v201.charging_station import ChargingStation
from ocpp_sdk.v201.csms import CSMS
from ocpp_sdk.v201.csms import ChargingStation as Session
from ocpp_sdk.v201.provisioning import (
    BootNotificationRequest,
    BootNotificationResponse,
    GetVariablesRequest,
    GetVariablesResponse,
    SetVariablesRequest,
    SetVariablesResponse,
)
from ocpp_sdk.v201.remotecontrol import (
    RequestStartTransactionRequest,
    RequestStartTransactionResponse,
)
from ocpp_sdk.v201.transactions import TransactionEventRequest, TransactionEventResponse
from ocpp_sdk.v201.types import (
    AuthorizationStatus,
    Component,
    GetVariableData,
    GetVariableResult,
    GetVariableStatus,
    IdToken,
    IdTokenEnum,
    IdTokenInfo,
    RegistrationStatus,
    RequestStartStopStatus,
    SetVariableData,
    SetVariableResult,
    SetVariableStatus,
    Variable,
)
from ocpp_sdk.v201.types import (
    ChargingStation as StationInfo,
)
from tests.schema import samples

NOW = datetime(2025, 3, 14, 9, 26, 53, tzinfo=UTC)
REGISTRY = new_registry()
SCHEMAS = Path(__file__).resolve().parents[2] / "docs" / "spec" / "2.0.1" / "schemas"
TOKEN = IdToken(id_token="TAG", type=IdTokenEnum.CENTRAL)


class Csms(ch.UnimplementedProvisioningHandler):
    def __init__(self) -> None:
        self.seen: list[str] = []

    def on_boot_notification(
        self, charging_station: Session, request: BootNotificationRequest
    ) -> BootNotificationResponse:
        self.seen.append(f"Boot:{request.charging_station.model}")
        return BootNotificationResponse(
            current_time=NOW, interval=300, status=RegistrationStatus.ACCEPTED
        )


class CsmsAuth(ch.UnimplementedAuthorizationHandler):
    async def on_authorize(
        self, charging_station: Session, request: AuthorizeRequest
    ) -> AuthorizeResponse:
        return AuthorizeResponse(id_token_info=IdTokenInfo(status=AuthorizationStatus.ACCEPTED))


class CsmsTransactions(ch.UnimplementedTransactionsHandler):
    def on_transaction_event(
        self, charging_station: Session, request: TransactionEventRequest
    ) -> TransactionEventResponse:
        return TransactionEventResponse(total_cost=1.5)


class StationRemote(csh.UnimplementedRemoteControlHandler):
    def __init__(self) -> None:
        self.started: list[int] = []

    def on_request_start_transaction(
        self, request: RequestStartTransactionRequest
    ) -> RequestStartTransactionResponse:
        self.started.append(request.remote_start_id)
        return RequestStartTransactionResponse(status=RequestStartStopStatus.ACCEPTED)


class StationProvisioning(csh.UnimplementedProvisioningHandler):
    async def on_get_variables(self, request: GetVariablesRequest) -> GetVariablesResponse:
        return GetVariablesResponse(
            get_variable_result=[
                GetVariableResult(
                    attribute_status=GetVariableStatus.ACCEPTED,
                    component=d.component,
                    variable=d.variable,
                    attribute_value="60",
                )
                for d in request.get_variable_data
            ]
        )

    def on_set_variables(self, request: SetVariablesRequest) -> SetVariablesResponse:
        return SetVariablesResponse(
            set_variable_result=[
                SetVariableResult(
                    attribute_status=SetVariableStatus.ACCEPTED,
                    component=d.component,
                    variable=d.variable,
                )
                for d in request.set_variable_data
            ]
        )


@pytest.fixture
async def csms() -> AsyncIterator[tuple[CSMS, Csms]]:
    handler = Csms()
    server = CSMS(
        csms_module.Config(
            provisioning=handler, authorization=CsmsAuth(), transactions=CsmsTransactions()
        ),
        port=0,
        ping_interval=None,
    )
    await server.start()
    try:
        yield server, handler
    finally:
        await server.shutdown(timeout=3)


async def test_boot_authorize_transaction_and_csms_calls(csms: tuple[CSMS, Csms]) -> None:
    server, handler = csms
    remote = StationRemote()
    config = cs_module.Config(remote_control=remote, provisioning=StationProvisioning())
    url = f"ws://127.0.0.1:{server.port}/ocpp/CS-1"
    async with ChargingStation(url, config, ping_interval=None, reconnect=None) as station:
        boot = await station.boot_notification(
            BootNotificationRequest(
                charging_station=StationInfo(model="X1", vendor_name="Acme"),
                reason="PowerUp",
            )
        )
        assert boot.status is RegistrationStatus.ACCEPTED and boot.interval == 300
        auth = await station.authorize(AuthorizeRequest(id_token=TOKEN))
        assert auth.id_token_info.status is AuthorizationStatus.ACCEPTED
        event = await station.transaction_event(
            TransactionEventRequest.model_validate(
                {
                    "eventType": "Started",
                    "timestamp": "2025-03-14T09:26:53Z",
                    "triggerReason": "Authorized",
                    "seqNo": 0,
                    "transactionInfo": {"transactionId": "T1"},
                }
            )
        )
        assert event.total_cost == 1.5
        assert handler.seen == ["Boot:X1"]

        # the CSMS calls the station
        started = await server.request_start_transaction(
            "CS-1", RequestStartTransactionRequest(id_token=TOKEN, remote_start_id=7)
        )
        assert started.status is RequestStartStopStatus.ACCEPTED and remote.started == [7]
        got = await server.get_variables(
            "CS-1",
            GetVariablesRequest(
                get_variable_data=[
                    GetVariableData(
                        component=Component(name="OCPPCommCtrlr"),
                        variable=Variable(name="HeartbeatInterval"),
                    )
                ]
            ),
        )
        assert got.get_variable_result[0].attribute_value == "60"
        session = server.charge_point("CS-1")
        assert session is not None and session.charge_point_id == "CS-1"
        done = await session.set_variables(
            SetVariablesRequest(
                set_variable_data=[
                    SetVariableData(
                        attribute_value="30",
                        component=Component(name="OCPPCommCtrlr"),
                        variable=Variable(name="HeartbeatInterval"),
                    )
                ]
            )
        )
        assert done.set_variable_result[0].attribute_status is SetVariableStatus.ACCEPTED

        # a block without a handler answers NotSupported; so does an unimplemented message
        with pytest.raises(CallError) as info:
            await station.heartbeat(HeartbeatRequest())
        assert info.value.code == "NotSupported"


async def test_offline_and_unknown_station() -> None:
    server = CSMS(port=0, ping_interval=None)
    await server.start()
    try:
        station = ChargingStation("ws://127.0.0.1:1/ocpp/CS-9", reconnect=None)
        with pytest.raises(NotConnectedError):
            await station.boot_notification(
                BootNotificationRequest(
                    charging_station=StationInfo(model="X", vendor_name="V"),
                    reason="PowerUp",
                )
            )
        with pytest.raises(NotConnectedError):
            await server.get_variables(
                "CS-9",
                GetVariablesRequest(
                    get_variable_data=[
                        GetVariableData(component=Component(name="C"), variable=Variable(name="V"))
                    ]
                ),
            )
    finally:
        await server.shutdown(timeout=3)


def snake(action: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", action).lower()


class Echoing:
    """A handler for every message: checks the request is the sample and answers the sample."""

    def __init__(self, with_session: bool) -> None:
        self.with_session = with_session
        self.handled: list[str] = []

    def __getattr__(self, name: str) -> Callable[..., BaseModel]:
        if not name.startswith("on_"):
            raise AttributeError(name)
        action = next(a for a in REGISTRY.actions() if snake(a) == name[3:])

        def handle(*args: BaseModel) -> BaseModel:
            assert (not self.with_session) or hasattr(args[0], "charge_point_id")
            _, request = samples.load(SCHEMAS, f"{action}Request")
            assert REGISTRY.encode(args[-1]) == request
            self.handled.append(action)
            _, response = samples.load(SCHEMAS, f"{action}Response")
            return REGISTRY.decode_response(action, response)

        return handle


@pytest.fixture
async def pair() -> AsyncIterator[tuple[CSMS, ChargingStation, Echoing, Echoing]]:
    csms_handler, station_handler = Echoing(True), Echoing(False)
    any_csms: Any = csms_handler
    any_station: Any = station_handler
    csms_config = csms_module.Config(**{f: any_csms for f in _fields(ch)})
    station_config = cs_module.Config(**{f: any_station for f in _fields(csh)})
    server = CSMS(csms_config, port=0, ping_interval=None)
    await server.start()
    station = ChargingStation(
        f"ws://127.0.0.1:{server.port}/ocpp/CS-1",
        station_config,
        ping_interval=None,
        reconnect=None,
    )
    await station.__aenter__()
    try:
        yield server, station, csms_handler, station_handler
    finally:
        await station.close()
        await server.shutdown(timeout=3)


def _fields(module: Any) -> set[str]:
    return {field for field, _ in module.DISPATCH.values()}


STATION_SENDS = sorted(set(REGISTRY.actions()) - set(csh.DISPATCH) | {"DataTransfer"})
CSMS_SENDS = sorted(csh.DISPATCH)


@pytest.mark.parametrize("action", STATION_SENDS)
async def test_station_to_csms(
    pair: tuple[CSMS, ChargingStation, Echoing, Echoing], action: str
) -> None:
    _, station, csms_handler, _ = pair
    _, payload = samples.load(SCHEMAS, f"{action}Request")
    answer = await getattr(station, snake(action))(REGISTRY.decode_request(action, payload))
    _, expected = samples.load(SCHEMAS, f"{action}Response")
    assert REGISTRY.encode(answer) == expected
    assert csms_handler.handled == [action]


@pytest.mark.parametrize("action", CSMS_SENDS)
async def test_csms_to_station(
    pair: tuple[CSMS, ChargingStation, Echoing, Echoing], action: str
) -> None:
    server, _, _, station_handler = pair
    _, payload = samples.load(SCHEMAS, f"{action}Request")
    request = REGISTRY.decode_request(action, payload)
    answer = await getattr(server, snake(action))("CS-1", request)
    _, expected = samples.load(SCHEMAS, f"{action}Response")
    assert REGISTRY.encode(answer) == expected
    session = server.charge_point("CS-1")
    assert session is not None
    assert REGISTRY.encode(await getattr(session, snake(action))(request)) == expected
    assert station_handler.handled == [action, action]


def test_the_two_sides_cover_all_messages_and_the_configs_match() -> None:
    import dataclasses

    assert set(STATION_SENDS) | set(CSMS_SENDS) == set(REGISTRY.actions())
    assert set(STATION_SENDS) & set(CSMS_SENDS) == {"DataTransfer"}
    assert {f.name for f in dataclasses.fields(cs_module.Config)} == _fields(csh)
    assert {f.name for f in dataclasses.fields(csms_module.Config)} == _fields(ch)
    assert len(csh.DISPATCH) == 40 and len(ch.DISPATCH) == 25  # 64: 24 + 39 + DataTransfer


def test_unimplemented_bases_answer_not_supported() -> None:
    for module, extra in ((csh, ()), (ch, (None,))):
        for name in dir(module):
            if name.startswith("Unimplemented"):
                handler = getattr(module, name)()
                for method in (m for m in dir(handler) if m.startswith("on_")):
                    with pytest.raises(CallError) as info:
                        getattr(handler, method)(*extra, object())
                    assert info.value.code == "NotSupported"
