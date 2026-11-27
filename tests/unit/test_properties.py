"""Property tests (Hypothesis): nothing the peer sends may crash the SDK, and whatever it
accepts round-trips. ``fuzz.yml`` runs them with a large example count.

Failing examples found by the fuzzer are added below as explicit tests (``test_regression_*``).
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from ocpp_sdk import datetime as ocpp_datetime
from ocpp_sdk.errors import CallError, ValidationError
from ocpp_sdk.ocppj import Endpoint, Registry
from ocpp_sdk.ocppj.frames import (
    Call,
    CallErrorFrame,
    CallResult,
    FrameError,
    encode,
    parse_frame,
)
from ocpp_sdk.v16 import new_registry as new_registry_16
from ocpp_sdk.v21 import new_registry as new_registry_21
from ocpp_sdk.v201 import new_registry as new_registry_201
from ocpp_sdk.versions import Version
from tests.schema import samples

ROOT = Path(__file__).resolve().parents[2]
FIXTURES_16 = ROOT / "tests" / "fixtures" / "v16"
SCHEMAS = {
    Version.OCPP201: ROOT / "docs" / "spec" / "2.0.1" / "schemas",
    Version.OCPP21: ROOT / "docs" / "spec" / "2.1" / "schemas",
}
REGISTRIES: dict[Version, Registry] = {
    Version.OCPP16: new_registry_16(),
    Version.OCPP201: new_registry_201(),
    Version.OCPP21: new_registry_21(),
}
MESSAGE_VERSIONS = [Version.OCPP16, Version.OCPP201, Version.OCPP21]
VERSIONS = [Version.OCPP16, Version.OCPP201, Version.OCPP21]

json_scalars = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text()
)
json_values = st.recursive(
    json_scalars,
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4)
    ),
    max_leaves=12,
)
json_objects = st.dictionaries(st.text(max_size=12), json_values, max_size=6)
unique_ids = st.text(min_size=1, max_size=36)


def sample_payloads(version: Version) -> list[tuple[str, str, dict[str, Any]]]:
    """``(action, "request" | "response", full valid payload)`` for every message."""
    out = []
    registry = REGISTRIES[version]
    for action in sorted(registry.actions()):
        for part in ("request",) if registry.is_one_way(action) else ("request", "response"):
            if version is Version.OCPP16:
                payload = json.loads((FIXTURES_16 / f"{action}.json").read_text())[part]
            else:
                stem = action if registry.is_one_way(action) else f"{action}{part.capitalize()}"
                _, payload = samples.load(SCHEMAS[version], stem)
            out.append((action, part, payload))
    return out


SAMPLES = {v: sample_payloads(v) for v in MESSAGE_VERSIONS}


# --------------------------------------------------------------------------- frames


@pytest.mark.parametrize("version", VERSIONS)
@given(raw=st.text(max_size=200))
def test_parse_frame_never_raises_anything_but_frame_error(version: Version, raw: str) -> None:
    try:
        parse_frame(raw, version)
    except FrameError as err:
        assert 1 <= len(err.unique_id) <= 36 or err.unique_id == "-1"


@pytest.mark.parametrize("version", VERSIONS)
@given(data=st.lists(json_values, max_size=6))
def test_parse_frame_on_json_arrays(version: Version, data: list[Any]) -> None:
    try:
        frame = parse_frame(json.dumps(data), version)
    except FrameError:
        return
    assert isinstance(frame, Call | CallResult | CallErrorFrame)
    assert 0 < len(frame.unique_id) <= 36


valid_frames = st.one_of(
    st.builds(
        Call, unique_id=unique_ids, action=st.text(min_size=1, max_size=30), payload=json_objects
    ),
    st.builds(CallResult, unique_id=unique_ids, payload=json_objects),
    st.builds(
        CallErrorFrame,
        unique_id=unique_ids,
        code=st.text(min_size=1, max_size=30),
        description=st.text(max_size=255),
        details=json_objects,
    ),
)


@pytest.mark.parametrize("version", VERSIONS)
@given(frame=valid_frames)
def test_encode_then_parse_is_the_identity(
    version: Version, frame: Call | CallResult | CallErrorFrame
) -> None:
    assert parse_frame(encode(frame), version) == frame


# --------------------------------------------------------------------------- date-times


@given(text=st.text(max_size=40))
def test_datetime_parse_never_crashes(text: str) -> None:
    try:
        parsed = ocpp_datetime.parse(text)
    except ValidationError:
        return
    assert parsed.utcoffset() == timedelta(0)


@given(
    moment=st.datetimes(
        min_value=datetime(1970, 1, 2),
        max_value=datetime(9998, 12, 30),
        timezones=st.timezones() | st.just(UTC),
    )
)
def test_datetime_format_then_parse_keeps_the_instant_to_the_millisecond(moment: datetime) -> None:
    text = ocpp_datetime.format(moment)
    assert text.endswith("Z")
    parsed = ocpp_datetime.parse(text)
    expected = moment.astimezone(UTC).replace(
        microsecond=moment.astimezone(UTC).microsecond // 1000 * 1000
    )
    assert parsed == expected
    assert ocpp_datetime.format(parsed) == text


@given(moment=st.datetimes(timezones=st.timezones()))
def test_datetime_format_of_any_aware_value_is_valid_or_a_clear_error(moment: datetime) -> None:
    try:
        text = ocpp_datetime.format(moment)
    except (ValidationError, OverflowError):
        return
    ocpp_datetime.parse(text)


# --------------------------------------------------------------------------- messages


def mutate(value: Any, data: st.DataObject, depth: int = 0) -> Any:
    """A copy of ``value`` with random fields dropped, replaced or duplicated."""
    roll = data.draw(st.integers(0, 9), label="mutation")
    if roll == 0 and depth > 0:
        return data.draw(json_values, label="replacement")
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if data.draw(st.integers(0, 14)) == 0:
                continue  # drop the key
            out[key] = mutate(item, data, depth + 1)
        if data.draw(st.integers(0, 14)) == 0:
            out[data.draw(st.text(max_size=6))] = data.draw(json_values)
        return out
    if isinstance(value, list):
        items = [mutate(x, data, depth + 1) for x in value]
        if items and data.draw(st.integers(0, 9)) == 0:
            items = items * 2
        if data.draw(st.integers(0, 14)) == 0:
            items = []
        return items
    return value


def check_request(registry: Registry, action: str, payload: Any) -> None:
    try:
        message = registry.decode_request(action, payload)
    except CallError as err:
        assert err.code and err.description is not None
        return
    wire = registry.encode(message)
    again = registry.decode_request(action, wire)
    assert again == message
    assert registry.encode(again) == wire


def check_response(registry: Registry, action: str, payload: Any) -> None:
    try:
        message = registry.decode_response(action, payload)
    except ValidationError:
        return
    wire = registry.encode(message)
    again = registry.decode_response(action, wire)
    assert again == message
    assert registry.encode(again) == wire


@pytest.mark.parametrize("version", MESSAGE_VERSIONS)
@given(data=st.data())
def test_mutated_messages_never_crash_and_accepted_ones_round_trip(
    version: Version, data: st.DataObject
) -> None:
    registry = REGISTRIES[version]
    action, part, payload = data.draw(st.sampled_from(SAMPLES[version]))
    mutated = mutate(payload, data)
    (check_request if part == "request" else check_response)(registry, action, mutated)


@pytest.mark.parametrize("version", MESSAGE_VERSIONS)
@given(data=st.data(), payload=json_objects)
def test_arbitrary_objects_never_crash_decoding(
    version: Version, data: st.DataObject, payload: dict[str, Any]
) -> None:
    registry = REGISTRIES[version]
    action = data.draw(st.sampled_from([*sorted(registry.actions()), "Unknown"]))
    check_request(registry, action, payload)
    if action != "Unknown" and not registry.is_one_way(action):
        check_response(registry, action, payload)


@pytest.mark.parametrize("version", MESSAGE_VERSIONS)
def test_every_full_sample_is_accepted_and_round_trips(version: Version) -> None:
    for action, part, payload in SAMPLES[version]:
        (check_request if part == "request" else check_response)(
            REGISTRIES[version], action, payload
        )
        message = (
            REGISTRIES[version].decode_request(action, payload)
            if part == "request"
            else REGISTRIES[version].decode_response(action, payload)
        )
        assert REGISTRIES[version].encode(message) == payload


# --------------------------------------------------------------------------- endpoint


async def _feed(version: Version, frames: list[str]) -> list[str]:
    registry = REGISTRIES[version]
    sent: list[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    def handler(action: str, request: BaseModel) -> BaseModel:
        return registry.response_type(action).model_validate(
            dict(next(p for a, part, p in SAMPLES[version] if a == action and part == "response"))
        )

    endpoint = Endpoint(registry, send, handler=handler)
    for raw in frames:
        endpoint.feed(raw)
    for _ in range(5):
        await asyncio.sleep(0)
    await endpoint.close()
    return sent


frame_texts = st.one_of(
    st.text(max_size=80),
    st.lists(json_values, max_size=5).map(json.dumps),
    st.builds(
        lambda uid, action, payload: json.dumps([2, uid, action, payload]),
        unique_ids,
        st.sampled_from(["Heartbeat", "Authorize", "BootNotification", "Nope", ""]),
        json_values,
    ),
    st.builds(lambda uid, payload: json.dumps([3, uid, payload]), unique_ids, json_values),
    st.builds(
        lambda uid, action, payload: json.dumps([6, uid, action, payload]),
        unique_ids,
        st.sampled_from(["NotifyPeriodicEventStream", "Heartbeat", "Nope"]),
        json_values,
    ),
    st.builds(
        lambda uid, code: json.dumps([5, uid, code, "d", {}]), unique_ids, st.text(max_size=10)
    ),
    st.builds(
        lambda uid, code: json.dumps([4, uid, code, "d", {}]), unique_ids, st.text(max_size=10)
    ),
)


@pytest.mark.parametrize("version", MESSAGE_VERSIONS)
@given(frames=st.lists(frame_texts, max_size=8))
def test_endpoint_survives_any_frames_and_only_sends_valid_ones(
    version: Version, frames: list[str]
) -> None:
    sent = asyncio.run(_feed(version, frames))
    for raw in sent:
        frame = parse_frame(raw, version)
        assert isinstance(frame, CallResult | CallErrorFrame)


# --------------------------------------------------------------------------- regressions


def test_regression_sub_millisecond_fraction_is_sent_as_whole_seconds() -> None:
    """Found by the fuzzer: a microsecond value below 1 ms was sent as ``.000Z``."""
    moment = datetime(2000, 1, 1, 0, 0, 0, 1, tzinfo=UTC)
    assert ocpp_datetime.format(moment) == "2000-01-01T00:00:00Z"
    assert ocpp_datetime.format(moment.replace(microsecond=1500)) == "2000-01-01T00:00:00.001Z"
