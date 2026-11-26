"""Every OCPP 1.6 message crosses a real connection in the direction the spec gives it.

The sample payloads of ``tests/fixtures/v16`` are the requests and the answers; the handlers
check what they get and return the sample answer, so each feature profile (Core, Firmware
Management, Local Auth List Management, Reservation, Smart Charging, Remote Trigger) is
exercised on both sides.
"""

import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from ocpp_sdk.v16 import charge_point as cp_module
from ocpp_sdk.v16 import charge_point_handlers as cph
from ocpp_sdk.v16 import csms as csms_module
from ocpp_sdk.v16 import csms_handlers as ch
from ocpp_sdk.v16 import new_registry
from ocpp_sdk.v16.charge_point import ChargePoint
from ocpp_sdk.v16.csms import CSMS

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "v16"
REGISTRY = new_registry()


def sample(action: str, part: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((FIXTURES / f"{action}.json").read_text())[part]
    return payload


def snake(action: str) -> str:
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in action).lstrip("_")


class Echoing:
    """A handler for every message: checks the request is the sample and answers the sample."""

    def __init__(self, with_session: bool) -> None:
        self.with_session = with_session
        self.handled: list[str] = []

    def __getattr__(self, name: str) -> Callable[..., BaseModel]:
        if not name.startswith("on_"):
            raise AttributeError(name)
        action = "".join(part.title() for part in name[3:].split("_"))
        action = {"DataTransfer": "DataTransfer"}.get(action, action)

        def handle(*args: BaseModel) -> BaseModel:
            request = args[-1]
            assert (not self.with_session) or hasattr(args[0], "charge_point_id")
            assert REGISTRY.encode(request) == sample(action, "request")
            self.handled.append(action)
            return REGISTRY.decode_response(action, sample(action, "response"))

        return handle


@pytest.fixture
async def pair() -> AsyncIterator[tuple[CSMS, ChargePoint, Echoing, Echoing]]:
    csms_handler, station_handler = Echoing(with_session=True), Echoing(with_session=False)
    any_csms: Any = csms_handler
    any_station: Any = station_handler
    csms_config = csms_module.Config(core=any_csms, firmware=any_csms, security=any_csms)
    station_config = cp_module.Config(
        core=any_station,
        firmware=any_station,
        local_auth_list=any_station,
        reservation=any_station,
        smart_charging=any_station,
        remote_trigger=any_station,
        security=any_station,
    )
    server = CSMS(csms_config, port=0, ping_interval=None)
    await server.start()
    station = ChargePoint(
        f"ws://127.0.0.1:{server.port}/ocpp/CP-1",
        station_config,
        ping_interval=None,
        reconnect=None,
    )
    await station.__aenter__()
    try:
        yield server, station, csms_handler, station_handler
    finally:
        await station.close()
        await server.shutdown(timeout=3)


STATION_SENDS = sorted(set(REGISTRY.actions()) - set(cph.DISPATCH) | {"DataTransfer"})
CSMS_SENDS = sorted(cph.DISPATCH)


@pytest.mark.parametrize("action", STATION_SENDS)
async def test_station_to_csms(
    pair: tuple[CSMS, ChargePoint, Echoing, Echoing], action: str
) -> None:
    _, station, csms_handler, _ = pair
    request = REGISTRY.decode_request(action, sample(action, "request"))
    answer = await getattr(station, snake(action))(request)
    assert REGISTRY.encode(answer) == sample(action, "response")
    assert csms_handler.handled == [action]


@pytest.mark.parametrize("action", CSMS_SENDS)
async def test_csms_to_station(
    pair: tuple[CSMS, ChargePoint, Echoing, Echoing], action: str
) -> None:
    server, _, _, station_handler = pair
    request = REGISTRY.decode_request(action, sample(action, "request"))
    answer = await getattr(server, snake(action))("CP-1", request)
    assert REGISTRY.encode(answer) == sample(action, "response")
    assert station_handler.handled == [action]
    # the same through the session object
    session = server.charge_point("CP-1")
    assert session is not None
    again = await getattr(session, snake(action))(request)
    assert REGISTRY.encode(again) == sample(action, "response")


def test_the_two_sides_cover_all_messages() -> None:
    assert set(STATION_SENDS) | set(CSMS_SENDS) == set(REGISTRY.actions())
    assert set(STATION_SENDS) & set(CSMS_SENDS) == {"DataTransfer"}
    assert set(ch.DISPATCH) == set(STATION_SENDS)
