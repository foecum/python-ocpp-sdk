"""OCPP 2.1 Charging Station: connects to a CSMS and exchanges messages.

Example:
    >>> from ocpp_sdk.v21.charging_station import ChargingStation, Config
    >>> cp = ChargingStation("ws://localhost:9000/ocpp/CS-1", Config())
    >>> cp.connected
    False
"""

from __future__ import annotations

import logging
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import TracebackType

from pydantic import BaseModel

from ocpp_sdk._internal.lifecycle import StationCore
from ocpp_sdk.ocppj.endpoint import DEFAULT_QUEUE_SIZE, DEFAULT_RESPONSE_TIMEOUT
from ocpp_sdk.transport.client import Reconnect
from ocpp_sdk.transport.connection import Connection
from ocpp_sdk.v21 import new_registry
from ocpp_sdk.v21.charging_station_handlers import (
    DISPATCH,
    AuthorizationHandler,
    AvailabilityHandler,
    BatterySwapHandler,
    BidirectionalHandler,
    ChargingStationCalls,
    DataTransferHandler,
    DERControlHandler,
    DiagnosticsHandler,
    DisplayMessageHandler,
    FirmwareHandler,
    ISO15118Handler,
    LocalAuthListHandler,
    ProvisioningHandler,
    RemoteControlHandler,
    ReservationHandler,
    SecurityHandler,
    SmartChargingHandler,
    TariffAndCostHandler,
    TransactionsHandler,
)
from ocpp_sdk.versions import Version

__all__ = ["ChargingStation", "Config"]

logger = logging.getLogger("ocpp_sdk.v21.charging_station")

_RECONNECT = Reconnect()


@dataclass
class Config:
    """The handlers of the messages a Charging Station receives, one per functional block.

    A block left as ``None`` is answered ``NotSupported``. Subclass the matching
    ``Unimplemented<Block>Handler`` to implement only some of a block's messages.

    ``send_handler(message)`` (sync or async) receives the unconfirmed messages (OCPP 2.1 SEND)
    the CSMS sends; there are none in the standard, so it is for vendor use. Without one they
    are logged and dropped.

    Example:
        >>> from ocpp_sdk.v21.charging_station import Config
        >>> from ocpp_sdk.v21.charging_station_handlers import UnimplementedProvisioningHandler
        >>> Config(provisioning=UnimplementedProvisioningHandler()).security is None
        True
    """

    security: SecurityHandler | None = None
    provisioning: ProvisioningHandler | None = None
    authorization: AuthorizationHandler | None = None
    local_auth_list: LocalAuthListHandler | None = None
    transactions: TransactionsHandler | None = None
    remote_control: RemoteControlHandler | None = None
    availability: AvailabilityHandler | None = None
    reservation: ReservationHandler | None = None
    tariff_and_cost: TariffAndCostHandler | None = None
    smart_charging: SmartChargingHandler | None = None
    firmware: FirmwareHandler | None = None
    iso15118: ISO15118Handler | None = None
    diagnostics: DiagnosticsHandler | None = None
    display_message: DisplayMessageHandler | None = None
    data_transfer: DataTransferHandler | None = None
    bidirectional: BidirectionalHandler | None = None
    der_control: DERControlHandler | None = None
    battery_swap: BatterySwapHandler | None = None
    send_handler: Callable[[BaseModel], Awaitable[None] | None] | None = None


class ChargingStation(ChargingStationCalls):
    """An OCPP 2.1 Charging Station (the client side).

    Args:
        url: ``ws://`` or ``wss://`` URL of the CSMS ending in the charge point ID.
        config: Handlers for the messages the CSMS sends.
        password: HTTP Basic password (security profiles 1 and 2).
        ssl_context: TLS context for ``wss://`` (profiles 2 and 3).
        reconnect: Back-off after a lost connection (OCPP-J 5.4); ``None`` disables it.
        response_timeout: Default seconds to wait for an answer to a call.
        queue_size: How many calls may wait behind the outstanding one.
        ping_interval, ping_timeout, max_message_size, open_timeout, close_timeout:
            Passed to the transport :class:`~ocpp_sdk.transport.client.Client`.

    Offline, calls fail fast with ``NotConnectedError``; nothing is queued or retried, and the
    station never sends BootNotification or Heartbeat on its own.

    Example:
        >>> async def main() -> None:  # doctest: +SKIP
        ...     async with ChargingStation("ws://localhost:9000/ocpp/CS-1") as cp:
        ...         await cp.heartbeat(HeartbeatRequest())
    """

    def __init__(
        self,
        url: str,
        config: Config | None = None,
        *,
        password: str | None = None,
        ssl_context: ssl.SSLContext | None = None,
        reconnect: Reconnect | None = _RECONNECT,
        response_timeout: float = DEFAULT_RESPONSE_TIMEOUT,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        ping_interval: float | None = 30.0,
        ping_timeout: float | None = 10.0,
        max_message_size: int = 1024 * 1024,
        open_timeout: float = 10.0,
        close_timeout: float = 5.0,
    ) -> None:
        cfg = config or Config()
        self._core = StationCore(
            url,
            version=Version.OCPP21,
            registry=new_registry(),
            config=cfg,
            send_handler=cfg.send_handler,
            dispatch=DISPATCH,
            response_timeout=response_timeout,
            queue_size=queue_size,
            password=password,
            ssl_context=ssl_context,
            reconnect=reconnect,
            ping_interval=ping_interval,
            ping_timeout=ping_timeout,
            max_message_size=max_message_size,
            open_timeout=open_timeout,
            close_timeout=close_timeout,
        )

    @property
    def connected(self) -> bool:
        """Whether a connection to the CSMS is up."""
        return self._core.connected

    @property
    def connection(self) -> Connection | None:
        """The live transport connection, or ``None`` while offline."""
        return self._core.connection

    async def wait_online(self) -> None:
        """Wait until a connection is up (returns at once if it already is).

        Unlike :meth:`wait_connected` this also works after a connection was lost and is
        restored by reconnecting.
        """
        await self._core.wait_online()

    def start(self) -> None:
        """Start connecting in the background (idempotent)."""
        self._core.start()

    async def wait_connected(
        self,
        timeout: float | None = None,  # noqa: ASYNC109 - public API takes a timeout
    ) -> Connection:
        """Wait until connected; see :meth:`~ocpp_sdk.transport.client.Client.wait_connected`."""
        return await self._core.wait_connected(timeout)

    async def close(self) -> None:
        """Close the connection and stop reconnecting."""
        await self._core.close()

    async def __aenter__(self) -> ChargingStation:
        await self._core.enter()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def _send(self, message: BaseModel) -> None:
        await self._core.send(message)

    async def _call(
        self,
        request: BaseModel,
        timeout: float | None,  # noqa: ASYNC109
    ) -> BaseModel:
        return await self._core.call(request, timeout)
