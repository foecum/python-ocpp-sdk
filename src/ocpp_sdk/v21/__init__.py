"""OCPP 2.1 messages, grouped by functional block.

OCPP 2.1 has its own types: it does not import ``ocpp_sdk.v201``.

Example:
    >>> from ocpp_sdk.v21 import new_registry
    >>> registry = new_registry()
    >>> len(registry.actions())
    91
    >>> registry.is_one_way("NotifyPeriodicEventStream")
    True
"""

from ocpp_sdk.ocppj.registry import Registry
from ocpp_sdk.v21 import (
    authorization,
    availability,
    batteryswap,
    bidirectional,
    datatransfer,
    dercontrol,
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
    bidirectional,
    dercontrol,
    batteryswap,
)


def new_registry() -> Registry:
    """A registry with every OCPP 2.1 message (91 actions, one of them unconfirmed)."""
    registry = Registry(Version.OCPP21)
    for module in _MODULES:
        for request, response in module.MESSAGES:
            registry.register(request, response)
        for message in getattr(module, "ONE_WAY", ()):
            registry.register_one_way(message)
    return registry
