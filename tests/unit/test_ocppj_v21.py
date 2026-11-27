"""OCPP 2.1 framing: SEND ([6, ...]) and CALLRESULTERROR ([5, ...])."""

import asyncio
import json
import logging
from typing import Any

import pytest
from pydantic import BaseModel

from ocpp_sdk.errors import NotConnectedError, ValidationError
from ocpp_sdk.ocppj import Endpoint, Registry
from ocpp_sdk.ocppj.frames import (
    CallResultErrorFrame,
    FrameError,
    Send,
    encode,
    parse_frame,
)
from ocpp_sdk.versions import Version
from tests.unit.ocppj_models import (
    EchoRequest,
    EchoResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    StreamRequest,
)
from tests.unit.test_endpoint import NOW, Wire


def registry(version: Version = Version.OCPP21) -> Registry:
    reg = Registry(version)
    reg.register(HeartbeatRequest, HeartbeatResponse)
    reg.register(EchoRequest, EchoResponse)
    reg.register_one_way(StreamRequest)
    return reg


async def settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


# ------------------------------------------------------------------ frames


def test_send_and_call_result_error_frames_round_trip() -> None:
    send = Send("id1", "Stream", {"seq": 1})
    assert encode(send) == '[6,"id1","Stream",{"seq":1}]'
    assert parse_frame(encode(send), Version.OCPP21) == send
    err = CallResultErrorFrame("id2", "FormatViolation", "bad", {"a": 1})
    assert encode(err) == '[5,"id2","FormatViolation","bad",{"a":1}]'
    assert parse_frame(encode(err), Version.OCPP21) == err
    short = parse_frame('[5,"id3","GenericError","x"]', Version.OCPP21)
    assert short == CallResultErrorFrame("id3", "GenericError", "x", {})
    assert parse_frame('[6,"id4","Stream",null]', Version.OCPP21) == Send("id4", "Stream", {})


@pytest.mark.parametrize(
    "raw",
    [
        '[6,"id"]',
        '[6,"id","Stream"]',
        '[6,"id","",{}]',
        '[6,"id",5,{}]',
        '[6,"id","Stream",[1]]',
        '[6,5,"Stream",{}]',
        '[6,"id","Stream",{},1]',
        '[5,"id","C"]',
        '[5,"id",1,"d",{}]',
        '[5,"id","C",5,{}]',
        '[5,"id","C","d",[1]]',
        '[5,5,"C","d",{}]',
    ],
)
def test_malformed_send_and_result_error_are_never_answered(raw: str) -> None:
    with pytest.raises(FrameError) as info:
        parse_frame(raw, Version.OCPP21)
    assert info.value.reply is False


def test_send_and_call_result_error_are_unknown_types_before_2_1() -> None:
    with pytest.raises(FrameError) as old:
        parse_frame('[6,"id","Stream",{}]', Version.OCPP16)
    assert old.value.reply is False
    with pytest.raises(FrameError) as v201:
        parse_frame('[5,"id","C","d",{}]', Version.OCPP201)
    assert v201.value.code == "MessageTypeNotSupported"


# ------------------------------------------------------------------ registry


def test_one_way_registration() -> None:
    reg = registry()
    assert reg.is_one_way("Stream") and not reg.is_one_way("Heartbeat")
    assert "Stream" in reg.actions()
    assert reg.decode_request("Stream", {"seq": 1}) == StreamRequest(seq=1)
    with pytest.raises(KeyError):
        reg.response_type("Stream")
    with pytest.raises(ValueError, match="already registered"):
        reg.register_one_way(StreamRequest)
    with pytest.raises(ValueError, match="already registered"):
        reg.register_one_way(HeartbeatRequest)


def test_response_error_code_follows_the_first_issue() -> None:
    reg = registry()
    assert (
        reg.response_error_code(ValidationError("x", issues=[{"field": "a", "type": "missing"}]))
        == "OccurrenceConstraintViolation"
    )
    assert reg.response_error_code(ValidationError("x")) == "PropertyConstraintViolation"


# ------------------------------------------------------------------ sending


async def test_send_writes_a_frame_without_waiting_or_queueing() -> None:
    wire = Wire()
    async with Endpoint(registry(), wire.send, id_factory=lambda: "s1") as endpoint:
        call = asyncio.create_task(endpoint.call(HeartbeatRequest(), timeout=5))  # outstanding
        await wire.wait_for(1)
        await endpoint.send(StreamRequest(seq=2))  # goes out while the CALL is outstanding
        assert json.loads(wire.sent[1]) == [6, "s1", "Stream", {"seq": 2}]
        call.cancel()
        await asyncio.gather(call, return_exceptions=True)


async def test_send_and_call_reject_the_wrong_kind_of_message() -> None:
    wire = Wire()
    async with Endpoint(registry(), wire.send) as endpoint:
        with pytest.raises(ValueError, match="use send"):
            await endpoint.call(StreamRequest(seq=1))
        with pytest.raises(ValueError, match="use call"):
            await endpoint.send(HeartbeatRequest())
        with pytest.raises(ValidationError):
            await endpoint.send(StreamRequest.model_construct(seq=1, note="too long for it"))
        wire.fail = OSError("gone")
        with pytest.raises(NotConnectedError, match="send failed"):
            await endpoint.send(StreamRequest(seq=1))
    with pytest.raises(NotConnectedError):
        await endpoint.send(StreamRequest(seq=1))


# ------------------------------------------------------------------ receiving SEND


async def test_incoming_sends_reach_the_handler_in_order_and_are_never_answered() -> None:
    wire = Wire()
    seen: list[int] = []

    async def handler(action: str, message: BaseModel) -> None:
        assert isinstance(message, StreamRequest) and action == "Stream"
        await asyncio.sleep(0.01)  # a slow handler must not reorder or overlap
        seen.append(message.seq)

    async with Endpoint(registry(), wire.send, send_handler=handler) as endpoint:
        for i in range(5):
            endpoint.feed(json.dumps([6, f"u{i}", "Stream", {"seq": i}]))
        await asyncio.sleep(0.2)
    assert seen == [0, 1, 2, 3, 4]
    assert wire.sent == []


async def test_a_sync_send_handler_works() -> None:
    wire = Wire()
    seen: list[str] = []
    async with Endpoint(
        registry(), wire.send, send_handler=lambda a, m: seen.append(a)
    ) as endpoint:
        endpoint.feed('[6,"u","Stream",{"seq":1}]')
        await settle()
    assert seen == ["Stream"]


async def test_bad_sends_are_dropped_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    wire = Wire()
    seen: list[str] = []

    def failing(action: str, message: BaseModel) -> None:
        seen.append(action)
        raise RuntimeError("boom")

    caplog.set_level(logging.WARNING, logger="ocpp_sdk.ocppj.endpoint")
    async with Endpoint(registry(), wire.send, send_handler=failing) as endpoint:
        endpoint.feed('[6,"a","Stream",{"seq":"x"}]')  # invalid payload
        endpoint.feed('[6,"b","Heartbeat",{}]')  # needs an answer: not allowed as SEND
        endpoint.feed('[6,"c","Unknown",{}]')
        endpoint.feed('[6,"d","Stream",{"seq":1}]')  # reaches the handler, which fails
        endpoint.feed('[6,"e","Stream",{"seq":2}]')  # and the next one still does
        await settle()
    assert seen == ["Stream", "Stream"]
    text = caplog.text
    assert "invalid SEND" in text and "needs an answer" in text and "failed" in text
    assert wire.sent == []


async def test_without_a_send_handler_sends_are_dropped(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="ocpp_sdk.ocppj.endpoint")
    async with Endpoint(registry(), Wire().send) as endpoint:
        endpoint.feed('[6,"a","Stream",{"seq":1}]')
        await settle()
    assert "no handler" in caplog.text


async def test_the_send_queue_is_bounded_and_drops_the_newest(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="ocpp_sdk.ocppj.endpoint")
    gate = asyncio.Event()
    seen: list[int] = []

    async def handler(action: str, message: BaseModel) -> None:
        await gate.wait()
        assert isinstance(message, StreamRequest)
        seen.append(message.seq)

    async with Endpoint(registry(), Wire().send, send_handler=handler, queue_size=2) as endpoint:
        for i in range(5):
            endpoint.feed(json.dumps([6, f"u{i}", "Stream", {"seq": i}]))
        await settle()  # the frames arrive together: two are queued, three are dropped
        gate.set()
        await asyncio.sleep(0.05)
    assert seen == [0, 1]
    assert caplog.text.count("queue is full") == 3


async def test_a_call_of_a_one_way_message_is_answered_with_protocol_error() -> None:
    wire = Wire()
    async with Endpoint(
        registry(), wire.send, handler=lambda a, r: HeartbeatResponse(current_time=NOW)
    ) as endpoint:
        endpoint.feed('[2,"c1","Stream",{"seq":1}]')
        await wire.wait_for(1)
    frame = json.loads(wire.sent[0])
    assert frame[:3] == [4, "c1", "ProtocolError"]


# ------------------------------------------------------------------ CALLRESULTERROR


async def test_an_undecodable_result_is_answered_with_call_result_error_in_2_1_only() -> None:
    for version, expected in ((Version.OCPP21, True), (Version.OCPP201, False)):
        wire = Wire()
        async with Endpoint(registry(version), wire.send, id_factory=lambda: "k1") as endpoint:
            call = asyncio.create_task(endpoint.call(HeartbeatRequest(), timeout=5))
            await wire.wait_for(1)
            endpoint.feed('[3,"k1",{"currentTime":"never"}]')
            with pytest.raises(ValidationError):
                await call
            await settle()
        sent: list[Any] = [json.loads(t) for t in wire.sent[1:]]
        if expected:
            assert sent[0][:3] == [5, "k1", "PropertyConstraintViolation"]
        else:
            assert sent == []


async def test_incoming_call_result_error_goes_to_the_handler_or_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="ocpp_sdk.ocppj.endpoint")
    async with Endpoint(registry(), Wire().send) as endpoint:
        endpoint.feed('[5,"r1","FormatViolation","bad",{}]')
        await settle()
    assert "rejected our response r1" in caplog.text

    got: list[CallResultErrorFrame] = []

    async def on_error(frame: CallResultErrorFrame) -> None:
        got.append(frame)

    async with Endpoint(registry(), Wire().send, result_error_handler=on_error) as endpoint:
        endpoint.feed('[5,"r2","GenericError","x",{"a":1}]')
        await settle()
    assert got == [CallResultErrorFrame("r2", "GenericError", "x", {"a": 1})]

    def broken(frame: CallResultErrorFrame) -> None:
        raise RuntimeError("no")

    async with Endpoint(registry(), Wire().send, result_error_handler=broken) as endpoint:
        endpoint.feed('[5,"r3","GenericError","x",{}]')
        await settle()
    assert "CALLRESULTERROR handler failed" in caplog.text
