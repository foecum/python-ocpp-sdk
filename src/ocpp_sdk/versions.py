"""OCPP protocol versions and their WebSocket subprotocol names."""

from __future__ import annotations

from enum import StrEnum


class Version(StrEnum):
    """An OCPP-J version; the value is the WebSocket subprotocol name.

    Example:
        >>> Version.OCPP16.value
        'ocpp1.6'
    """

    OCPP16 = "ocpp1.6"
    OCPP201 = "ocpp2.0.1"
    OCPP21 = "ocpp2.1"
