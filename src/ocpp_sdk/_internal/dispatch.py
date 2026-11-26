"""Turns a ``Config`` of handlers and a generated dispatch table into an endpoint handler."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from ocpp_sdk.errors import CallError
from ocpp_sdk.ocppj.endpoint import Handler

__all__ = ["make_handler"]

logger = logging.getLogger("ocpp_sdk.dispatch")


def make_handler(
    config: object,
    table: Mapping[str, tuple[str, str]],
    *leading: Any,
) -> Handler:
    """Build the ``handler(action, request)`` of an ``Endpoint``.

    ``table`` maps an action to the ``Config`` field and the handler method that serve it. A
    missing field (``None``) or an action that is not in the table is answered ``NotSupported``.
    ``leading`` arguments (the CSMS passes its session) go before the request. Handlers may be
    sync or async.
    """

    async def handle(action: str, request: BaseModel) -> BaseModel:
        entry = table.get(action)
        handler = getattr(config, entry[0]) if entry is not None else None
        if entry is None or handler is None:
            raise CallError("NotSupported", f"{action} is not supported")
        result = getattr(handler, entry[1])(*leading, request)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, BaseModel):
            logger.error("the handler of %s returned %r, not a response model", action, result)
            raise TypeError(f"the handler of {action} returned no response")
        return result

    return handle
