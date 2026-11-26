"""OCPP 2.0.1 messages, grouped by functional block.

Example:
    >>> from ocpp_sdk.v201 import new_registry
    >>> registry = new_registry()
    >>> len(registry.actions())
    64
    >>> type(registry.decode_request("Heartbeat", {})).__name__
    'HeartbeatRequest'
"""

from ocpp_sdk.ocppj.registry import Registry
from ocpp_sdk.v201 import (
    authorization,
    availability,
    datatransfer,
    diagnostics,
    displaymessage,
    firmware,
    iso15118,
    localauthlist,
    metervalues,
    provisioning,
    remotecontrol,
    reservation,
    security,
    smartcharging,
    tariffandcost,
    transactions,
)
from ocpp_sdk.versions import Version

__all__ = ["new_registry"]

_MODULES = (
    security,
    provisioning,
    authorization,
    localauthlist,
    transactions,
    remotecontrol,
    availability,
    reservation,
    tariffandcost,
    metervalues,
    smartcharging,
    firmware,
    iso15118,
    diagnostics,
    displaymessage,
    datatransfer,
)


def new_registry() -> Registry:
    """A registry with every OCPP 2.0.1 message (64 actions)."""
    registry = Registry(Version.OCPP201)
    for module in _MODULES:
        for request, response in module.MESSAGES:
            registry.register(request, response)
    return registry
