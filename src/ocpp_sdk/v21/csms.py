"""OCPP 2.1 CSMS: accepts Charging Stations and exchanges messages.

Example:
    >>> from ocpp_sdk.v21.csms import CSMS, Config
    >>> csms = CSMS(Config(), port=0)
    >>> csms.charge_point_ids()
    []
"""

from __future__ import annotations

import logging
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import TracebackType

from pydantic import BaseModel

from ocpp_sdk._internal.lifecycle import CSMSCore, SessionCore
from ocpp_sdk.ocppj.endpoint import DEFAULT_QUEUE_SIZE, DEFAULT_RESPONSE_TIMEOUT
from ocpp_sdk.transport.connection import Connection
from ocpp_sdk.v21 import new_registry
from ocpp_sdk.v21.csms_handlers import (
    DISPATCH,
    AuthorizationHandler,
    AvailabilityHandler,
    BatterySwapHandler,
    CSMSCalls,
    DataTransferHandler,
    DERControlHandler,
    DiagnosticsHandler,
    DisplayMessageHandler,
    FirmwareHandler,
    ISO15118Handler,
    MeterValuesHandler,
    ProvisioningHandler,
    ReservationHandler,
    SecurityHandler,
    SmartChargingHandler,
    StationCalls,
    TransactionsHandler,
)
from ocpp_sdk.versions import Version

__all__ = ["CSMS", "ChargingStation", "Config"]

logger = logging.getLogger("ocpp_sdk.v21.csms")

_MaybeAwaitable = Awaitable[object] | object


@dataclass
class Config:
    """The handlers of the messages a CSMS receives, one per functional block.

    A block left as ``None`` is answered ``NotSupported``. Handlers get the
    :class:`ChargingStation` session first. ``send_handler(station, message)`` (sync or async)
    receives the unconfirmed messages (OCPP 2.1 SEND) of the stations, such as
    ``NotifyPeriodicEventStream``, one at a time in arrival order; without one they are logged
    and dropped.

    Example:
        >>> from ocpp_sdk.v21.csms import Config
        >>> Config().provisioning is None
        True
    """

    security: SecurityHandler | None = None
    provisioning: ProvisioningHandler | None = None
    authorization: AuthorizationHandler | None = None
    transactions: TransactionsHandler | None = None
    availability: AvailabilityHandler | None = None
    reservation: ReservationHandler | None = None
    meter_values: MeterValuesHandler | None = None
    smart_charging: SmartChargingHandler | None = None
    firmware: FirmwareHandler | None = None
    iso15118: ISO15118Handler | None = None
    diagnostics: DiagnosticsHandler | None = None
    display_message: DisplayMessageHandler | None = None
    data_transfer: DataTransferHandler | None = None
    der_control: DERControlHandler | None = None
    battery_swap: BatterySwapHandler | None = None
    send_handler: Callable[[ChargingStation, BaseModel], _MaybeAwaitable] | None = None


class ChargingStation(StationCalls):
    """A connected Charging Station, as the Central System sees it.

    A session belongs to one connection: after the station reconnects, the handlers get a new
    session object and the old one raises ``NotConnectedError``.

    Example:
        >>> async def on_connect(station: ChargingStation) -> None:  # doctest: +SKIP
        ...     print(station.charge_point_id)
    """

    def __init__(self, core: SessionCore) -> None:
        self._core = core

    @property
    def charge_point_id(self) -> str:
        """The station's ID, from the URL path."""
        return self._core.charge_point_id

    @property
    def connection(self) -> Connection:
        """The transport connection (address, TLS certificate, ...)."""
        return self._core.connection

    @property
    def connected(self) -> bool:
        """Whether this session's connection is still up."""
        return self._core.connected

    async def _call(
        self,
        request: BaseModel,
        timeout: float | None,  # noqa: ASYNC109
    ) -> BaseModel:
        return await self._core.call(request, timeout)


class CSMS(CSMSCalls):
    """An OCPP 2.1 CSMS (the server side).

    Args:
        config: Handlers for the messages the stations send.
        host, port: Where to listen (``port=0`` picks a free one; see :attr:`port`).
        ssl_context: Enables TLS (security profiles 2 and 3).
        known_id: ``known_id(charge_point_id)``; false answers HTTP 404.
        authenticate: ``authenticate(charge_point_id, password)``; enables HTTP Basic auth.
        check_certificate_identity, operator_name: Security profile 3 checks.
        on_connect, on_disconnect: Called with the :class:`ChargingStation` session when a station
            connects / its connection ended (sync or async).
        response_timeout: Default seconds to wait for an answer to a call.
        queue_size: How many calls may wait behind the outstanding one.
        ping_interval, ping_timeout, max_message_size, open_timeout, close_timeout:
            Passed to the transport :class:`~ocpp_sdk.transport.server.Server`.

    Example:
        >>> async def main() -> None:  # doctest: +SKIP
        ...     async with CSMS(Config(core=MyCoreHandler())) as csms:
        ...         await csms.reset("CS-1", ResetRequest(type=Reset.IMMEDIATE))
    """

    def __init__(
        self,
        config: Config | None = None,
        *,
        host: str = "127.0.0.1",
        port: int = 9000,
        ssl_context: ssl.SSLContext | None = None,
        known_id: Callable[[str], _MaybeAwaitable] | None = None,
        authenticate: Callable[[str, str], _MaybeAwaitable] | None = None,
        check_certificate_identity: bool = False,
        operator_name: str | None = None,
        on_connect: Callable[[ChargingStation], _MaybeAwaitable] | None = None,
        on_disconnect: Callable[[ChargingStation], _MaybeAwaitable] | None = None,
        response_timeout: float = DEFAULT_RESPONSE_TIMEOUT,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        ping_interval: float | None = 30.0,
        ping_timeout: float | None = 10.0,
        max_message_size: int = 1024 * 1024,
        open_timeout: float = 10.0,
        close_timeout: float = 5.0,
    ) -> None:
        cfg = config or Config()
        self._core = CSMSCore(
            version=Version.OCPP21,
            registry=new_registry(),
            config=cfg,
            send_handler=cfg.send_handler,
            dispatch=DISPATCH,
            wrap=ChargingStation,
            on_connect=on_connect,
            on_disconnect=on_disconnect,
            response_timeout=response_timeout,
            queue_size=queue_size,
            host=host,
            port=port,
            ssl_context=ssl_context,
            known_id=known_id,
            authenticate=authenticate,
            check_certificate_identity=check_certificate_identity,
            operator_name=operator_name,
            ping_interval=ping_interval,
            ping_timeout=ping_timeout,
            max_message_size=max_message_size,
            open_timeout=open_timeout,
            close_timeout=close_timeout,
        )

    async def start(self) -> None:
        """Start listening."""
        await self._core.start()

    @property
    def port(self) -> int:
        """The port actually listening."""
        return self._core.port

    def charge_point_ids(self) -> list[str]:
        """The IDs of the connected stations, in identity order."""
        return self._core.ids()

    def charge_point(self, charge_point_id: str) -> ChargingStation | None:
        """The session of a connected station, or ``None``."""
        return self._core.session(charge_point_id)

    async def for_each(self, fn: Callable[[ChargingStation], _MaybeAwaitable]) -> None:
        """Call ``fn(session)`` for every connected station, in identity order (sync or async)."""
        await self._core.for_each(fn)

    async def shutdown(
        self,
        timeout: float = 10.0,  # noqa: ASYNC109 - public API takes a timeout
    ) -> None:
        """Stop accepting, close every connection with 1001 and wait up to ``timeout`` s."""
        await self._core.shutdown(timeout)

    async def __aenter__(self) -> CSMS:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.shutdown()

    async def _call_charge_point(
        self,
        charge_point_id: str,
        request: BaseModel,
        timeout: float | None,  # noqa: ASYNC109
    ) -> BaseModel:
        return await self._core.call(charge_point_id, request, timeout)
