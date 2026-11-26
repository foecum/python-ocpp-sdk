"""The connection object handed to the application, and the sink that consumes frames."""

from __future__ import annotations

from typing import Any, Protocol

from websockets.asyncio.client import ClientConnection
from websockets.asyncio.server import ServerConnection

from ocpp_sdk.versions import Version

__all__ = ["Connection", "FrameSink"]


class FrameSink(Protocol):
    """Receives every text frame of a connection; ``ocppj.Endpoint`` is one."""

    def feed(self, raw: str) -> None:
        """Handle one received text frame (must not block)."""

    async def close(self) -> None:
        """The connection ended: fail waiting calls, stop tasks."""


class Connection:
    """One live OCPP-J WebSocket connection.

    Attributes:
        charge_point_id: The station's ID (from the URL path).
        version: The negotiated protocol version.
        remote_address: Peer address as reported by the socket.
        peer_certificate: The peer's TLS certificate (``getpeercert()`` dict), if any.
    """

    def __init__(
        self,
        websocket: ServerConnection | ClientConnection,
        charge_point_id: str,
        version: Version,
        peer_certificate: dict[str, Any] | None = None,
    ) -> None:
        self._ws = websocket
        self.charge_point_id = charge_point_id
        self.version = version
        self.remote_address: Any = websocket.remote_address
        self.peer_certificate = peer_certificate

    async def send(self, text: str) -> None:
        """Send one text frame; raises ``websockets.ConnectionClosed`` if the link is gone."""
        await self._ws.send(text)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Close with the WebSocket close handshake."""
        await self._ws.close(code, reason)
