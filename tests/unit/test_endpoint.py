import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel

from ocpp_sdk.errors import (
    CallError,
    CallTimeoutError,
    NotConnectedError,
    QueueFullError,
    ValidationError,
)
from ocpp_sdk.ocppj.endpoint import Endpoint
from ocpp_sdk.ocppj.registry import Registry
from ocpp_sdk.versions import Version
from tests.unit.ocppj_models import (
    EchoRequest,
    EchoResponse,
    HeartbeatRequest,
    HeartbeatResponse,
)

NOW = datetime(2025, 1, 1, tzinfo=UTC)


def registry(version: Version = Version.OCPP201) -> Registry:
    reg = Registry(version)
    reg.register(HeartbeatRequest, HeartbeatResponse)
    reg.register(EchoRequest, EchoResponse)
    return reg


def echo_handler(action: str, request: BaseModel) -> BaseModel:
    if isinstance(request, EchoRequest):
        return EchoResponse(text=request.text.upper())
    return HeartbeatResponse(current_time=NOW)


class Wire:
    """Records frames an endpoint sends; can inject frames into it."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail: Exception | None = None
        self.event = asyncio.Event()

    async def send(self, text: str) -> None:
        if self.fail:
            raise self.fail
        self.sent.append(text)
        self.event.set()

    async def wait_for(self, n: int) -> None:
        while len(self.sent) < n:
            self.event.clear()
            await asyncio.wait_for(self.event.wait(), 2)

    def frame(self, i: int = -1) -> list[Any]:
        result: list[Any] = json.loads(self.sent[i])
        return result


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.fixture
async def wire() -> Wire:
    return Wire()


def pair(
    handler_b: Callable[..., Any] | None = echo_handler,
    version: Version = Version.OCPP201,
    **kwargs: Any,
) -> tuple[Endpoint, Endpoint]:
    holder: dict[str, Endpoint] = {}

    async def send_a(text: str) -> None:
        holder["b"].feed(text)

    async def send_b(text: str) -> None:
        holder["a"].feed(text)

    holder["a"] = Endpoint(registry(version), send_a, **kwargs)
    holder["b"] = Endpoint(registry(version), send_b, handler=handler_b)
    return holder["a"], holder["b"]


# ------------------------------------------------------------------ round trip


async def test_call_round_trip() -> None:
    a, b = pair()
    async with a, b:
        response = await a.call(EchoRequest(text="hi"))
        assert response == EchoResponse(text="HI")
        beat = await a.call(HeartbeatRequest())
        assert isinstance(beat, HeartbeatResponse)
        assert beat.current_time == NOW


async def test_async_handler_and_sync_handler() -> None:
    async def slow(action: str, request: BaseModel) -> BaseModel:
        await asyncio.sleep(0)
        return echo_handler(action, request)

    for handler in (slow, echo_handler):
        a, b = pair(handler)
        async with a, b:
            assert await a.call(EchoRequest(text="x")) == EchoResponse(text="X")


async def test_call_error_from_peer() -> None:
    def refuse(action: str, request: BaseModel) -> BaseModel:
        raise CallError("NotSupported", "no", {"why": 1})

    a, b = pair(refuse)
    async with a, b:
        with pytest.raises(CallError) as info:
            await a.call(EchoRequest(text="x"))
        assert (info.value.code, info.value.description, info.value.details) == (
            "NotSupported",
            "no",
            {"why": 1},
        )


async def test_call_error_code_is_spelled_for_version() -> None:
    def refuse(action: str, request: BaseModel) -> BaseModel:
        raise CallError("FormatViolation", "bad")

    a, b = pair(refuse, Version.OCPP16)
    async with a, b:
        with pytest.raises(CallError) as info:
            await a.call(EchoRequest(text="x"))
        assert info.value.code == "FormationViolation"


async def test_handler_can_call_back_into_the_peer() -> None:
    holder: dict[str, Endpoint] = {}

    async def handler(action: str, request: BaseModel) -> BaseModel:
        inner = await holder["b"].call(EchoRequest(text="inner"))
        assert isinstance(inner, EchoResponse)
        return EchoResponse(text=f"outer+{inner.text}")

    a, b = pair(handler)
    holder["b"] = b
    # a must also answer b's call
    a._handler = echo_handler
    async with a, b:
        assert await a.call(EchoRequest(text="x")) == EchoResponse(text="outer+INNER")


# -------------------------------------------------------------- incoming CALLs


async def test_incoming_call_answers(wire: Wire) -> None:
    async with Endpoint(registry(), wire.send, handler=echo_handler) as ep:
        ep.feed('[2,"7","Echo",{"text":"ab"}]')
        await wire.wait_for(1)
        assert wire.frame() == [3, "7", {"text": "AB"}]


async def test_null_payload_is_accepted(wire: Wire) -> None:
    async with Endpoint(registry(), wire.send, handler=echo_handler) as ep:
        ep.feed('[2,"7","Heartbeat",null]')
        await wire.wait_for(1)
        assert wire.frame() == [3, "7", {"currentTime": "2025-01-01T00:00:00Z"}]


async def test_unknown_action_answers_not_implemented(wire: Wire) -> None:
    async with Endpoint(registry(), wire.send, handler=echo_handler) as ep:
        ep.feed('[2,"7","Nope",{}]')
        await wire.wait_for(1)
        assert wire.frame()[:3] == [4, "7", "NotImplemented"]


async def test_no_handler_answers_not_implemented(wire: Wire) -> None:
    async with Endpoint(registry(), wire.send) as ep:
        ep.feed('[2,"7","Heartbeat",{}]')
        await wire.wait_for(1)
        assert wire.frame()[:3] == [4, "7", "NotImplemented"]


@pytest.mark.parametrize(
    ("version", "payload", "code"),
    [
        (Version.OCPP201, "{}", "OccurrenceConstraintViolation"),
        (Version.OCPP16, "{}", "OccurenceConstraintViolation"),
        (Version.OCPP201, '{"text":3}', "TypeConstraintViolation"),
        (Version.OCPP21, '{"text":"waytoolongtext"}', "PropertyConstraintViolation"),
    ],
)
async def test_invalid_payload_answers_constraint_violation(
    wire: Wire, version: Version, payload: str, code: str
) -> None:
    async with Endpoint(registry(version), wire.send, handler=echo_handler) as ep:
        ep.feed(f'[2,"7","Echo",{payload}]')
        await wire.wait_for(1)
        assert wire.frame()[:3] == [4, "7", code]


async def test_handler_exception_is_internal_error_without_text(
    wire: Wire, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(action: str, request: BaseModel) -> BaseModel:
        raise RuntimeError("secret detail")

    with caplog.at_level(logging.ERROR, logger="ocpp_sdk.ocppj.endpoint"):
        async with Endpoint(registry(), wire.send, handler=boom) as ep:
            ep.feed('[2,"7","Heartbeat",{}]')
            await wire.wait_for(1)
    assert wire.frame() == [4, "7", "InternalError", "", {}]
    assert "secret detail" not in wire.sent[0]
    assert "secret detail" in caplog.text


async def test_handler_returning_wrong_type_is_internal_error(wire: Wire) -> None:
    def wrong(action: str, request: BaseModel) -> BaseModel:
        return EchoResponse(text="x")

    async with Endpoint(registry(), wire.send, handler=wrong) as ep:
        ep.feed('[2,"7","Heartbeat",{}]')
        await wire.wait_for(1)
        assert wire.frame()[:3] == [4, "7", "InternalError"]


async def test_handler_returning_invalid_model_is_internal_error(wire: Wire) -> None:
    def invalid(action: str, request: BaseModel) -> BaseModel:
        return EchoResponse.model_construct(**{})

    async with Endpoint(registry(), wire.send, handler=invalid) as ep:
        ep.feed('[2,"7","Echo",{"text":"a"}]')
        await wire.wait_for(1)
        assert wire.frame()[:3] == [4, "7", "InternalError"]


async def test_reply_send_failure_is_swallowed(wire: Wire) -> None:
    wire.fail = ConnectionError("gone")
    async with Endpoint(registry(), wire.send, handler=echo_handler) as ep:
        ep.feed('[2,"7","Heartbeat",{}]')
        await settle()
    assert wire.sent == []


# ------------------------------------------------------------ malformed frames


@pytest.mark.parametrize(
    ("version", "raw", "expected"),
    [
        (Version.OCPP201, "garbage", [4, "-1", "RpcFrameworkError"]),
        (Version.OCPP16, "garbage", [4, "-1", "FormationViolation"]),
        (Version.OCPP201, '[2,"i","Echo","x"]', [4, "i", "RpcFrameworkError"]),
        (Version.OCPP201, '[9,"i","Echo",{}]', [4, "i", "MessageTypeNotSupported"]),
        (Version.OCPP201, '[2,5,"Echo",{}]', [4, "-1", "RpcFrameworkError"]),
    ],
)
async def test_malformed_frames_are_answered(
    wire: Wire, version: Version, raw: str, expected: list[Any]
) -> None:
    async with Endpoint(registry(version), wire.send, handler=echo_handler) as ep:
        ep.feed(raw)
        await wire.wait_for(1)
        assert wire.frame()[:3] == expected


@pytest.mark.parametrize("version", [Version.OCPP16, Version.OCPP21])
async def test_unknown_message_type_is_ignored_in_16_and_21(
    wire: Wire, version: Version, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="ocpp_sdk.ocppj.endpoint"):
        async with Endpoint(registry(version), wire.send) as ep:
            ep.feed('[9,"i","Echo",{}]')
            await settle()
    assert wire.sent == []
    assert "ignoring frame" in caplog.text


async def test_response_with_unknown_id_is_dropped(wire: Wire) -> None:
    async with Endpoint(registry(), wire.send) as ep:
        ep.feed('[3,"nope",{}]')
        ep.feed('[4,"nope","GenericError","",{}]')
        ep.feed('[3,"nope"]')
        await settle()
    assert wire.sent == []


# --------------------------------------------------------- responses to calls


async def test_invalid_response_fails_the_call(wire: Wire) -> None:
    ids = iter(["a1"])
    async with Endpoint(registry(), wire.send, id_factory=lambda: next(ids)) as ep:
        task = asyncio.create_task(ep.call(EchoRequest(text="x")))
        await wire.wait_for(1)
        ep.feed('[3,"a1",{"text":5}]')
        with pytest.raises(ValidationError):
            await task


async def test_malformed_result_for_outstanding_call_fails_it(wire: Wire) -> None:
    ids = iter(["a1"])
    async with Endpoint(registry(), wire.send, id_factory=lambda: next(ids)) as ep:
        task = asyncio.create_task(ep.call(EchoRequest(text="x")))
        await wire.wait_for(1)
        ep.feed('[3,"other"]')  # not ours: ignored
        ep.feed('[3,"a1"]')
        with pytest.raises(ValidationError, match="unusable"):
            await task


async def test_send_encodes_with_message_id_and_action(wire: Wire) -> None:
    ids = iter(["a1"])
    async with Endpoint(registry(), wire.send, id_factory=lambda: next(ids)) as ep:
        task = asyncio.create_task(ep.call(EchoRequest(text="x", count=2)))
        await wire.wait_for(1)
        assert wire.frame() == [2, "a1", "Echo", {"text": "x", "count": 2}]
        ep.feed('[3,"a1",{"text":"X"}]')
        assert await task == EchoResponse(text="X")


async def test_invalid_request_raises_before_sending(wire: Wire) -> None:
    async with Endpoint(registry(), wire.send) as ep:
        with pytest.raises(ValidationError):
            await ep.call(EchoRequest.model_construct(text=""))
    assert wire.sent == []


# ---------------------------------------------------- timeouts and cancelling


async def test_timeout_frees_the_slot_and_late_response_is_dropped(wire: Wire) -> None:
    ids = iter(["a1", "a2"])
    async with Endpoint(registry(), wire.send, id_factory=lambda: next(ids)) as ep:
        with pytest.raises(CallTimeoutError):
            await ep.call(EchoRequest(text="x"), timeout=0.02)
        ep.feed('[3,"a1",{"text":"late"}]')  # dropped
        task = asyncio.create_task(ep.call(EchoRequest(text="y")))
        await wire.wait_for(2)
        ep.feed('[3,"a2",{"text":"Y"}]')
        assert await task == EchoResponse(text="Y")


async def test_default_timeout_applies(wire: Wire) -> None:
    async with Endpoint(registry(), wire.send, response_timeout=0.02) as ep:
        with pytest.raises(CallTimeoutError):
            await ep.call(HeartbeatRequest())


async def test_timeout_counts_from_send_not_from_queueing(wire: Wire) -> None:
    ids = iter(["a1", "a2"])
    async with Endpoint(registry(), wire.send, id_factory=lambda: next(ids)) as ep:
        first = asyncio.create_task(ep.call(EchoRequest(text="1"), timeout=1))
        second = asyncio.create_task(ep.call(EchoRequest(text="2"), timeout=0.15))
        await wire.wait_for(1)
        await asyncio.sleep(0.2)  # longer than the second call's timeout, but it was not sent
        ep.feed('[3,"a1",{"text":"1"}]')
        await first
        await wire.wait_for(2)
        ep.feed('[3,"a2",{"text":"2"}]')
        assert await second == EchoResponse(text="2")


async def test_cancelled_outstanding_call_frees_the_slot(wire: Wire) -> None:
    ids = iter(["a1", "a2"])
    async with Endpoint(registry(), wire.send, id_factory=lambda: next(ids)) as ep:
        first = asyncio.create_task(ep.call(EchoRequest(text="1")))
        second = asyncio.create_task(ep.call(EchoRequest(text="2")))
        await wire.wait_for(1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        await wire.wait_for(2)
        assert wire.frame()[1] == "a2"
        ep.feed('[3,"a2",{"text":"2"}]')
        assert await second == EchoResponse(text="2")


async def test_cancelled_queued_call_is_never_sent(wire: Wire) -> None:
    ids = iter(["a1", "a2", "a3"])
    async with Endpoint(registry(), wire.send, id_factory=lambda: next(ids)) as ep:
        first = asyncio.create_task(ep.call(EchoRequest(text="1")))
        second = asyncio.create_task(ep.call(EchoRequest(text="2")))
        third = asyncio.create_task(ep.call(EchoRequest(text="3")))
        await wire.wait_for(1)
        second.cancel()
        await settle()
        ep.feed('[3,"a1",{"text":"1"}]')
        await first
        await wire.wait_for(2)
        assert wire.frame()[1] == "a3"
        ep.feed('[3,"a3",{"text":"3"}]')
        await third
        assert len(wire.sent) == 2
        with pytest.raises(asyncio.CancelledError):
            await second


# ------------------------------------------------------------ queue and order


async def test_calls_are_sent_one_at_a_time_in_order(wire: Wire) -> None:
    ids = iter(f"a{i}" for i in range(5))
    async with Endpoint(registry(), wire.send, id_factory=lambda: next(ids)) as ep:
        tasks = [asyncio.create_task(ep.call(EchoRequest(text=str(i)))) for i in range(5)]
        for i in range(5):
            await wire.wait_for(i + 1)
            await settle()
            assert len(wire.sent) == i + 1  # the next is held back until this one is answered
            ep.feed(f'[3,"a{i}",{{"text":"{i}"}}]')
        results = await asyncio.gather(*tasks)
        assert [r.text for r in results] == ["0", "1", "2", "3", "4"]  # type: ignore[attr-defined]
        assert [json.loads(s)[1] for s in wire.sent] == [f"a{i}" for i in range(5)]


async def test_queue_is_bounded(wire: Wire) -> None:
    async with Endpoint(registry(), wire.send, queue_size=2) as ep:
        tasks = [asyncio.create_task(ep.call(HeartbeatRequest()))]
        await wire.wait_for(1)  # one outstanding
        tasks += [asyncio.create_task(ep.call(HeartbeatRequest())) for _ in range(2)]
        await settle()  # two queued behind it
        with pytest.raises(QueueFullError):
            await ep.call(HeartbeatRequest())
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_default_queue_size_is_1000(wire: Wire) -> None:
    async with Endpoint(registry(), wire.send) as ep:
        tasks = [asyncio.create_task(ep.call(HeartbeatRequest()))]
        await wire.wait_for(1)
        tasks += [asyncio.create_task(ep.call(HeartbeatRequest())) for _ in range(1000)]
        await settle()
        with pytest.raises(QueueFullError):
            await ep.call(HeartbeatRequest())
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_concurrent_calls_both_directions() -> None:
    a, b = pair()
    a._handler = echo_handler
    async with a, b:
        results = await asyncio.gather(
            *[a.call(EchoRequest(text=f"a{i}")) for i in range(20)],
            *[b.call(EchoRequest(text=f"b{i}")) for i in range(20)],
        )
        assert [r.text for r in results] == [  # type: ignore[attr-defined]
            *[f"A{i}" for i in range(20)],
            *[f"B{i}" for i in range(20)],
        ]


# ------------------------------------------------------------------ lifecycle


async def test_send_failure_is_not_connected_and_slot_is_free(wire: Wire) -> None:
    wire.fail = ConnectionResetError("reset")
    async with Endpoint(registry(), wire.send) as ep:
        with pytest.raises(NotConnectedError, match="send failed"):
            await ep.call(HeartbeatRequest())
        wire.fail = None
        task = asyncio.create_task(ep.call(HeartbeatRequest(), timeout=0.02))
        with pytest.raises(CallTimeoutError):
            await task
        assert len(wire.sent) == 1


async def test_close_fails_outstanding_and_queued_calls(wire: Wire) -> None:
    ep = Endpoint(registry(), wire.send)
    first = asyncio.create_task(ep.call(HeartbeatRequest()))
    second = asyncio.create_task(ep.call(HeartbeatRequest()))
    await wire.wait_for(1)
    await ep.close()
    for task in (first, second):
        with pytest.raises(NotConnectedError):
            await task
    assert ep.closed
    with pytest.raises(NotConnectedError):
        await ep.call(HeartbeatRequest())
    await ep.close()  # idempotent
    ep.feed('[2,"7","Heartbeat",{}]')  # ignored once closed
    await settle()
    assert len(wire.sent) == 1


async def test_close_cancels_running_handlers_and_leaves_no_tasks(wire: Wire) -> None:
    started = asyncio.Event()

    async def hang(action: str, request: BaseModel) -> BaseModel:
        started.set()
        await asyncio.sleep(60)
        raise AssertionError("unreachable")

    ep = Endpoint(registry(), wire.send, handler=hang)
    ep.feed('[2,"7","Heartbeat",{}]')
    await asyncio.wait_for(started.wait(), 2)
    await ep.close()
    assert wire.sent == []
    others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    assert others == []


async def test_close_from_inside_a_handler(wire: Wire) -> None:
    holder: dict[str, Endpoint] = {}

    async def closing(action: str, request: BaseModel) -> BaseModel:
        await holder["ep"].close()
        return HeartbeatResponse(current_time=NOW)

    ep = Endpoint(registry(), wire.send, handler=closing)
    holder["ep"] = ep
    ep.feed('[2,"7","Heartbeat",{}]')
    await settle()
    assert ep.closed


async def test_worker_skips_a_call_cancelled_just_before_its_turn(wire: Wire) -> None:
    ids = iter(["a1", "a2", "a3"])
    async with Endpoint(registry(), wire.send, id_factory=lambda: next(ids)) as ep:
        first = asyncio.create_task(ep.call(EchoRequest(text="1")))
        second = asyncio.create_task(ep.call(EchoRequest(text="2")))
        third = asyncio.create_task(ep.call(EchoRequest(text="3")))
        await wire.wait_for(1)
        await settle()
        ep.feed('[3,"a1",{"text":"1"}]')
        second.cancel()  # the worker runs before the cancelled task removes itself
        await first
        await wire.wait_for(2)
        assert wire.frame()[1] == "a3"
        ep.feed('[3,"a3",{"text":"3"}]')
        await third
        await asyncio.gather(second, return_exceptions=True)
