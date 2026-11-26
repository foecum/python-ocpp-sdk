"""OCPP 1.6J messages, grouped by feature profile.

Example:
    >>> from ocpp_sdk.v16 import new_registry
    >>> registry = new_registry()
    >>> len(registry.actions())
    28
    >>> registry.decode_request("Authorize", {"idTag": "04A2B3"})
    AuthorizeRequest(id_tag='04A2B3')
"""

from ocpp_sdk.ocppj.registry import Registry
from ocpp_sdk.v16 import core, firmware, localauth, remotetrigger, reservation, smartcharging
from ocpp_sdk.versions import Version

__all__ = ["new_registry"]

_MODULES = (core, firmware, localauth, reservation, smartcharging, remotetrigger)


def new_registry() -> Registry:
    """A registry with every OCPP 1.6 message of the six feature profiles."""
    registry = Registry(Version.OCPP16)
    for module in _MODULES:
        for request, response in module.MESSAGES:
            registry.register(request, response)
    return registry
