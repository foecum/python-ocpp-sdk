"""The OCPP 1.6 ChargePoint and CSMS classes talking over a real loopback WebSocket."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedError
from websockets.typing import Subprotocol

from ocpp_sdk.errors import CallError, CallTimeoutError, NotConnectedError, ValidationError
from ocpp_sdk.transport import Reconnect
from ocpp_sdk.v16 import charge_point as cp_module
from ocpp_sdk.v16 import csms as csms_module
from ocpp_sdk.v16.charge_point import ChargePoint
from ocpp_sdk.v16.charge_point_handlers import (
    UnimplementedCoreHandler as StationCore,
)
from ocpp_sdk.v16.core import (
    AuthorizeConfirmation,
    AuthorizeRequest,
    BootNotificationConfirmation,
    BootNotificationRequest,
    ChangeAvailabilityRequest,
    DataTransferConfirmation,
    DataTransferRequest,
    HeartbeatConfirmation,
    HeartbeatRequest,
    MeterValuesConfirmation,
    MeterValuesRequest,
    RemoteStartTransactionConfirmation,
    RemoteStartTransactionRequest,
    ResetConfirmation,
    ResetRequest,
    StartTransactionConfirmation,
    StartTransactionRequest,
    StatusNotificationConfirmation,
    StatusNotificationRequest,
    StopTransactionConfirmation,
    StopTransactionRequest,
    UnlockConnectorRequest,
)
from ocpp_sdk.v16.csms import CSMS, Config
from ocpp_sdk.v16.csms import ChargePoint as Session
from ocpp_sdk.v16.csms_handlers import UnimplementedCoreHandler as CsmsCore
from ocpp_sdk.v16.csms_handlers import UnimplementedFirmwareHandler as CsmsFirmware
from ocpp_sdk.v16.firmware import (
    FirmwareStatusNotificationConfirmation,
    FirmwareStatusNotificationRequest,
)
from ocpp_sdk.v16.types import (
    AuthorizationStatus,
    AvailabilityType,
    ChargePointErrorCode,
    ChargePointStatus,
    DataTransferStatus,
    IdTagInfo,
    RegistrationStatus,
    RemoteStartStopStatus,
    ResetStatus,
    ResetType,
)
from tests.integration.helpers import until

NOW = datetime(2025, 3, 14, 9, 26, 53, tzinfo=UTC)
FAST = Reconnect(wait_minimum=0.05, random_range=0.0, repeat_times=1)


class CsmsCoreHandler(CsmsCore):
    """A Central System that accepts everything and remembers what it saw."""

    def __init__(self) -> None:
        self.seen: list[str] = []
        self.sessions: list[Session] = []

    def on_boot_notification(
        self, charge_point: Session, request: BootNotificationRequest
    ) -> BootNotificationConfirmation:  # sync handler
        self.seen.append("BootNotification")
        self.sessions.append(charge_point)
        return BootNotificationConfirmation(
            status=RegistrationStatus.ACCEPTED, current_time=NOW, interval=300
        )

    async def on_status_notification(
        self, charge_point: Session, request: StatusNotificationRequest
    ) -> StatusNotificationConfirmation:
        self.seen.append("StatusNotification")
        return StatusNotificationConfirmation()

    async def on_authorize(
        self, charge_point: Session, request: AuthorizeRequest
    ) -> AuthorizeConfirmation:
        self.seen.append("Authorize")
        return AuthorizeConfirmation(id_tag_info=IdTagInfo(status=AuthorizationStatus.ACCEPTED))

    async def on_start_transaction(
        self, charge_point: Session, request: StartTransactionRequest
    ) -> StartTransactionConfirmation:
        self.seen.append("StartTransaction")
        return StartTransactionConfirmation(
            id_tag_info=IdTagInfo(status=AuthorizationStatus.ACCEPTED), transaction_id=77
        )

    async def on_meter_values(
        self, charge_point: Session, request: MeterValuesRequest
    ) -> MeterValuesConfirmation:
        self.seen.append("MeterValues")
        return MeterValuesConfirmation()

    async def on_stop_transaction(
        self, charge_point: Session, request: StopTransactionRequest
    ) -> StopTransactionConfirmation:
        self.seen.append("StopTransaction")
        return StopTransactionConfirmation()

    async def on_heartbeat(
        self, charge_point: Session, request: HeartbeatRequest
    ) -> HeartbeatConfirmation:
        return HeartbeatConfirmation(current_time=NOW)


class StationCoreHandler(StationCore):
    """A Charge Point that accepts RemoteStartTransaction and Reset."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def on_remote_start_transaction(
        self, request: RemoteStartTransactionRequest
    ) -> RemoteStartTransactionConfirmation:
        self.seen.append(f"RemoteStart:{request.id_tag}")
        return RemoteStartTransactionConfirmation(status=RemoteStartStopStatus.ACCEPTED)

    async def on_reset(self, request: ResetRequest) -> ResetConfirmation:
        self.seen.append(f"Reset:{request.type}")
        return ResetConfirmation(status=ResetStatus.ACCEPTED)


@pytest.fixture
async def csms() -> AsyncIterator[tuple[CSMS, CsmsCoreHandler]]:
    handler = CsmsCoreHandler()
    server = CSMS(csms_module.Config(core=handler), port=0, ping_interval=None)
    await server.start()
    try:
        yield server, handler
    finally:
        await server.shutdown(timeout=3)


def url(server: CSMS, charge_point_id: str = "CP-1") -> str:
    return f"ws://127.0.0.1:{server.port}/ocpp/{charge_point_id}"


async def test_transaction_flow_and_calls_from_the_csms(
    csms: tuple[CSMS, CsmsCoreHandler],
) -> None:
    server, handler = csms
    station = StationCoreHandler()
    async with ChargePoint(
        url(server), cp_module.Config(core=station), ping_interval=None, reconnect=None
    ) as cp:
        assert cp.connected
        boot = await cp.boot_notification(
            BootNotificationRequest(charge_point_vendor="Acme", charge_point_model="X1")
        )
        assert boot.status is RegistrationStatus.ACCEPTED and boot.interval == 300
        await cp.status_notification(
            StatusNotificationRequest(
                connector_id=1,
                error_code=ChargePointErrorCode.NO_ERROR,
                status=ChargePointStatus.AVAILABLE,
            )
        )
        auth = await cp.authorize(AuthorizeRequest(id_tag="TAG"))
        assert auth.id_tag_info.status is AuthorizationStatus.ACCEPTED
        started = await cp.start_transaction(
            StartTransactionRequest(connector_id=1, id_tag="TAG", meter_start=0, timestamp=NOW)
        )
        assert started.transaction_id == 77
        await cp.meter_values(
            MeterValuesRequest.model_validate(
                {
                    "connectorId": 1,
                    "transactionId": 77,
                    "meterValue": [
                        {"timestamp": "2025-03-14T09:30:00Z", "sampledValue": [{"value": "5"}]}
                    ],
                }
            )
        )
        await cp.stop_transaction(
            StopTransactionRequest(meter_stop=10, timestamp=NOW, transaction_id=77)
        )
        assert handler.seen == [
            "BootNotification",
            "StatusNotification",
            "Authorize",
            "StartTransaction",
            "MeterValues",
            "StopTransaction",
        ]
        # the CSMS calls the station, by ID and through the session handed to its handler
        assert server.charge_point_ids() == ["CP-1"]
        remote = await server.remote_start_transaction(
            "CP-1", RemoteStartTransactionRequest(id_tag="REMOTE")
        )
        assert remote.status is RemoteStartStopStatus.ACCEPTED
        session = handler.sessions[0]
        assert session.charge_point_id == "CP-1" and session.connected
        reset = await session.reset(ResetRequest(type=ResetType.SOFT))
        assert reset.status is ResetStatus.ACCEPTED
        assert station.seen == ["RemoteStart:REMOTE", "Reset:Soft"]
    await until(lambda: server.charge_point_ids() == [])
    assert not session.connected


async def test_unsupported_and_unknown_messages(csms: tuple[CSMS, CsmsCoreHandler]) -> None:
    server, _ = csms
    async with ChargePoint(url(server), ping_interval=None, reconnect=None) as cp:
        # the station has no handlers: every CSMS request is NotSupported
        with pytest.raises(CallError) as info:
            await server.change_availability(
                "CP-1",
                ChangeAvailabilityRequest(connector_id=0, type=AvailabilityType.OPERATIVE),
            )
        assert info.value.code == "NotSupported"
        # the CSMS has no firmware handler
        with pytest.raises(CallError) as info:
            await cp.firmware_status_notification(
                FirmwareStatusNotificationRequest(status="Installed")
            )
        assert info.value.code == "NotSupported"
        # an action the SDK does not know
        async with connect(url(server, "RAW-1"), subprotocols=["ocpp1.6"]) as raw:  # type: ignore[list-item]
            await raw.send(json.dumps([2, "u1", "Frobnicate", {}]))
            answer = json.loads(await raw.recv())
            assert answer[:3] == [4, "u1", "NotImplemented"]
            # and a message that only a station sends, sent by the CSMS side's peer
            await raw.send(json.dumps([2, "u2", "Reset", {"type": "Soft"}]))
            assert json.loads(await raw.recv())[2] == "NotSupported"
            await raw.send(json.dumps([2, "u3", "Authorize", {"idTag": 5}]))
            assert json.loads(await raw.recv())[2] == "TypeConstraintViolation"


async def test_handler_errors(csms: tuple[CSMS, CsmsCoreHandler]) -> None:
    server, _ = csms

    class Failing(CsmsCoreHandler):
        async def on_authorize(
            self, charge_point: Session, request: AuthorizeRequest
        ) -> AuthorizeConfirmation:
            if request.id_tag == "SPECIFIC":
                raise CallError("SecurityError", "no")
            if request.id_tag == "NONE":
                return None  # type: ignore[return-value]
            raise RuntimeError("secret detail")

    server._core._config.core = Failing()  # type: ignore[attr-defined]
    async with ChargePoint(url(server), ping_interval=None, reconnect=None) as cp:
        with pytest.raises(CallError) as info:
            await cp.authorize(AuthorizeRequest(id_tag="SPECIFIC"))
        assert (info.value.code, info.value.description) == ("SecurityError", "no")
        for tag in ("BOOM", "NONE"):
            with pytest.raises(CallError) as info:
                await cp.authorize(AuthorizeRequest(id_tag=tag))
            assert info.value.code == "InternalError"
            assert "secret" not in str(info.value)


async def test_invalid_requests_never_reach_the_wire(csms: tuple[CSMS, CsmsCoreHandler]) -> None:
    server, handler = csms
    async with ChargePoint(url(server), ping_interval=None, reconnect=None) as cp:
        bad = AuthorizeRequest.model_construct(id_tag="x" * 30)
        with pytest.raises(ValidationError):
            await cp.authorize(bad)
        assert handler.seen == []


async def test_offline_calls_fail_fast_and_are_not_queued(
    csms: tuple[CSMS, CsmsCoreHandler],
) -> None:
    server, _ = csms
    cp = ChargePoint(url(server), ping_interval=None, reconnect=None)
    assert not cp.connected and cp.connection is None
    with pytest.raises(NotConnectedError):
        await cp.heartbeat(HeartbeatRequest())
    with pytest.raises(NotConnectedError):
        await server.reset("NOPE", ResetRequest(type=ResetType.HARD))
    async with cp:
        await cp.heartbeat(HeartbeatRequest())
    with pytest.raises(NotConnectedError):
        await cp.heartbeat(HeartbeatRequest())
    assert server.charge_point("CP-1") is None


async def test_response_timeout_and_slow_peer(csms: tuple[CSMS, CsmsCoreHandler]) -> None:
    server, _ = csms

    class Slow(StationCore):
        async def on_reset(self, request: ResetRequest) -> ResetConfirmation:
            await asyncio.sleep(1)
            return ResetConfirmation(status=ResetStatus.ACCEPTED)

    async with ChargePoint(
        url(server), cp_module.Config(core=Slow()), ping_interval=None, reconnect=None
    ):
        with pytest.raises(CallTimeoutError):
            await server.reset("CP-1", ResetRequest(type=ResetType.HARD), timeout=0.1)


async def test_connection_lost_mid_call_then_reconnect(csms: tuple[CSMS, CsmsCoreHandler]) -> None:
    server, _ = csms
    started = asyncio.Event()

    class Hanging(StationCore):
        async def on_reset(self, request: ResetRequest) -> ResetConfirmation:
            started.set()
            await asyncio.sleep(10)
            return ResetConfirmation(status=ResetStatus.ACCEPTED)

    async with ChargePoint(
        url(server), cp_module.Config(core=Hanging()), ping_interval=None, reconnect=FAST
    ) as cp:
        first = cp.connection
        call = asyncio.create_task(server.reset("CP-1", ResetRequest(type=ResetType.HARD)))
        await started.wait()
        assert first is not None
        await first.close(1012, "restart")  # the station drops the link while the call is open
        with pytest.raises(NotConnectedError):
            await call
        await until(lambda: cp.connected and cp.connection is not first)
        await until(lambda: server.charge_point("CP-1") is not None)
        # the new connection works and the CSMS got a fresh session
        assert (await cp.heartbeat(HeartbeatRequest())).current_time == NOW


async def test_duplicate_station_replaces_the_old_session_and_hooks_run() -> None:
    events: list[str] = []
    sessions: list[Session] = []
    gone: list[Session] = []

    async def on_connect(session: Session) -> None:
        events.append(f"up:{session.charge_point_id}")
        sessions.append(session)

    def on_disconnect(session: Session) -> None:
        events.append(f"down:{session.charge_point_id}")
        gone.append(session)

    server = CSMS(
        Config(core=CsmsCoreHandler()),
        port=0,
        ping_interval=None,
        on_connect=on_connect,
        on_disconnect=on_disconnect,
    )
    await server.start()
    try:
        async with ChargePoint(url(server), ping_interval=None, reconnect=None) as first:
            await first.heartbeat(HeartbeatRequest())
            async with ChargePoint(url(server), ping_interval=None, reconnect=None) as second:
                await until(lambda: not first.connected)
                assert (await second.heartbeat(HeartbeatRequest())).current_time == NOW
                assert server.charge_point("CP-1") is sessions[1]
                assert not sessions[0].connected
                with pytest.raises(NotConnectedError):
                    await sessions[0].reset(ResetRequest(type=ResetType.SOFT))
                await until(lambda: len(gone) == 1)  # the replaced session got its hook
                assert gone == [sessions[0]]
            await until(lambda: len(gone) == 2)
        assert events == ["up:CP-1", "up:CP-1", "down:CP-1", "down:CP-1"]
        assert gone == sessions
        assert server.charge_point_ids() == []
    finally:
        await server.shutdown(timeout=3)


async def test_a_failing_on_connect_hook_closes_the_session() -> None:
    sessions: list[Session] = []
    downs: list[Session] = []

    def on_connect(session: Session) -> None:
        sessions.append(session)
        raise RuntimeError("database is down")

    server = CSMS(
        Config(core=CsmsCoreHandler()),
        port=0,
        ping_interval=None,
        on_connect=on_connect,
        on_disconnect=downs.append,
    )
    await server.start()
    try:
        async with connect(url(server), subprotocols=[Subprotocol("ocpp1.6")]) as ws:
            with pytest.raises(ConnectionClosedError) as closed:
                await ws.recv()
        assert closed.value.rcvd is not None and closed.value.rcvd.code == 1011
        assert len(sessions) == 1 and not sessions[0].connected
        with pytest.raises(NotConnectedError):
            await sessions[0].reset(ResetRequest(type=ResetType.SOFT))
        assert server.charge_point_ids() == []
        assert downs == []  # on_disconnect only follows a successful on_connect
    finally:
        await server.shutdown(timeout=3)


async def test_for_each_visits_stations_in_identity_order() -> None:
    server = CSMS(Config(core=CsmsCoreHandler()), port=0, ping_interval=None)
    await server.start()
    visited: list[str] = []
    try:
        stations = [
            ChargePoint(url(server, name), ping_interval=None, reconnect=None)
            for name in ("CP-C", "CP-A", "CP-B")
        ]
        for st in stations:
            await st.__aenter__()
        assert server.charge_point_ids() == ["CP-A", "CP-B", "CP-C"]

        async def visit(session: Session) -> None:
            visited.append(session.charge_point_id)

        await server.for_each(visit)
        await server.for_each(lambda s: visited.append(s.charge_point_id.lower()))
        assert visited == ["CP-A", "CP-B", "CP-C", "cp-a", "cp-b", "cp-c"]
        for st in stations:
            await st.close()
    finally:
        await server.shutdown(timeout=3)


async def test_data_transfer_goes_both_ways() -> None:
    class Both(CsmsCore):
        def on_data_transfer(
            self, charge_point: Session, request: DataTransferRequest
        ) -> DataTransferConfirmation:
            return DataTransferConfirmation(status=DataTransferStatus.ACCEPTED, data="from-csms")

    class StationBoth(StationCore):
        def on_data_transfer(self, request: DataTransferRequest) -> DataTransferConfirmation:
            return DataTransferConfirmation(status=DataTransferStatus.REJECTED)

    server = CSMS(Config(core=Both()), port=0, ping_interval=None)
    await server.start()
    try:
        async with ChargePoint(
            url(server), cp_module.Config(core=StationBoth()), ping_interval=None, reconnect=None
        ) as cp:
            up = await cp.data_transfer(DataTransferRequest(vendor_id="v"))
            assert up.data == "from-csms"
            down = await server.data_transfer("CP-1", DataTransferRequest(vendor_id="v"))
            assert down.status is DataTransferStatus.REJECTED
    finally:
        await server.shutdown(timeout=3)


async def test_firmware_handler_and_unlock_default() -> None:
    class Firmware(CsmsFirmware):
        def on_firmware_status_notification(
            self, charge_point: Session, request: FirmwareStatusNotificationRequest
        ) -> FirmwareStatusNotificationConfirmation:
            return FirmwareStatusNotificationConfirmation()

    server = CSMS(Config(firmware=Firmware()), port=0, ping_interval=None)
    await server.start()
    try:
        async with ChargePoint(url(server), ping_interval=None, reconnect=None) as cp:
            await cp.firmware_status_notification(
                FirmwareStatusNotificationRequest.model_validate({"status": "Installed"})
            )
            with pytest.raises(CallError):  # an unimplemented handler method answers NotSupported
                await server.unlock_connector("CP-1", UnlockConnectorRequest(connector_id=1))
    finally:
        await server.shutdown(timeout=3)


async def test_unimplemented_bases_answer_not_supported_for_every_message() -> None:
    from ocpp_sdk.v16 import charge_point_handlers as cph
    from ocpp_sdk.v16 import csms_handlers as ch

    for module, extra in ((cph, ()), (ch, (None,))):
        for name in dir(module):
            if name.startswith("Unimplemented"):
                handler = getattr(module, name)()
                for method in (m for m in dir(handler) if m.startswith("on_")):
                    request = object()
                    with pytest.raises(CallError) as info:
                        getattr(handler, method)(*extra, request)
                    assert info.value.code == "NotSupported"


def test_config_fields_match_the_generated_dispatch_tables() -> None:
    import dataclasses

    from ocpp_sdk.v16 import charge_point_handlers as cph
    from ocpp_sdk.v16 import csms_handlers as ch

    assert {f.name for f in dataclasses.fields(cp_module.Config)} == {
        f for f, _ in cph.DISPATCH.values()
    }
    assert {f.name for f in dataclasses.fields(csms_module.Config)} == {
        f for f, _ in ch.DISPATCH.values()
    }
    assert len(cph.DISPATCH) == 26 and len(ch.DISPATCH) == 14  # 39 messages, DataTransfer both ways


def test_url_without_charge_point_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="charge point ID"):
        ChargePoint("ws://localhost:9000/")


async def test_for_each_skips_a_station_that_left_meanwhile() -> None:
    server = CSMS(Config(core=CsmsCoreHandler()), port=0, ping_interval=None)
    await server.start()
    visited: list[str] = []
    try:
        a = ChargePoint(url(server, "CP-A"), ping_interval=None, reconnect=None)
        b = ChargePoint(url(server, "CP-B"), ping_interval=None, reconnect=None)
        await a.__aenter__()
        await b.__aenter__()

        async def visit(session: Session) -> None:
            visited.append(session.charge_point_id)
            await b.close()
            await until(lambda: server.charge_point("CP-B") is None)

        await server.for_each(visit)
        assert visited == ["CP-A"]
        await a.close()
    finally:
        await server.shutdown(timeout=3)
