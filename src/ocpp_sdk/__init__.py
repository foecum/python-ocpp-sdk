"""Async Python SDK for OCPP-J (OCPP 1.6J, 2.0.1 and 2.1).

The everyday names are re-exported here; the messages live in ``ocpp_sdk.v16`` and
``ocpp_sdk.v201``, the WebSocket transport in ``ocpp_sdk.transport``.

Example:
    >>> import ocpp_sdk
    >>> isinstance(ocpp_sdk.__version__, str)
    True
    >>> issubclass(ocpp_sdk.NotConnectedError, ocpp_sdk.OCPPError)
    True
"""

from ocpp_sdk.errors import (
    CallError,
    CallTimeoutError,
    NotConnectedError,
    OCPPError,
    QueueFullError,
    ValidationError,
)
from ocpp_sdk.versions import Version

__version__ = "0.2.0"

__all__ = [
    "CallError",
    "CallTimeoutError",
    "NotConnectedError",
    "OCPPError",
    "QueueFullError",
    "ValidationError",
    "Version",
    "__version__",
]
