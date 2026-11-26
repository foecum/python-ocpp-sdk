from typing import Any

import pytest

from ocpp_sdk.ocppj.frames import (
    Call,
    CallErrorFrame,
    CallResult,
    FrameError,
    encode,
    framework_error_code,
    parse_frame,
)
from ocpp_sdk.versions import Version

ALL = [Version.OCPP16, Version.OCPP201, Version.OCPP21]


@pytest.mark.parametrize("version", ALL)
def test_parse_call(version: Version) -> None:
    frame = parse_frame('[2,"abc","Heartbeat",{"a":1}]', version)
    assert frame == Call("abc", "Heartbeat", {"a": 1})


@pytest.mark.parametrize("version", ALL)
def test_null_payload_is_empty_object(version: Version) -> None:
    assert parse_frame('[2,"abc","Heartbeat",null]', version) == Call("abc", "Heartbeat", {})
    assert parse_frame('[3,"abc",null]', version) == CallResult("abc", {})


def test_parse_result_and_error() -> None:
    assert parse_frame('[3,"x",{"k":"v"}]', Version.OCPP16) == CallResult("x", {"k": "v"})
    assert parse_frame('[4,"x","NotSupported","d",{"z":1}]', Version.OCPP16) == CallErrorFrame(
        "x", "NotSupported", "d", {"z": 1}
    )
    assert parse_frame('[4,"x","NotSupported",null,null]', Version.OCPP16) == CallErrorFrame(
        "x", "NotSupported"
    )
    assert parse_frame('[4,"x","NotSupported","d"]', Version.OCPP16) == CallErrorFrame(
        "x", "NotSupported", "d"
    )


def test_id_of_36_chars_ok_37_not() -> None:
    assert parse_frame(f'[3,"{"a" * 36}",{{}}]', Version.OCPP16) == CallResult("a" * 36, {})
    with pytest.raises(FrameError) as info:
        parse_frame(f'[2,"{"a" * 37}","Heartbeat",{{}}]', Version.OCPP16)
    assert info.value.unique_id == "-1"
    assert info.value.reply


@pytest.mark.parametrize(
    ("raw", "unique_id"),
    [
        ("not json", "-1"),
        ("NaN", "-1"),
        ('{"a":1}', "-1"),
        ("[]", "-1"),
        ("[2]", "-1"),
        ('["2","id","A",{}]', "id"),
        ('[true,"id","A",{}]', "id"),
        ('[2,5,"A",{}]', "-1"),
        ('[2,"","A",{}]', "-1"),
        ('[2,"id","A"]', "id"),
        ('[2,"id","A",{},1]', "id"),
        ('[2,"id",5,{}]', "id"),
        ('[2,"id","",{}]', "id"),
        ('[2,"id","A",[1]]', "id"),
        ('[2,"id","A","x"]', "id"),
        ("[" * 100000, "-1"),
    ],
)
@pytest.mark.parametrize("version", ALL)
def test_malformed_call_replies_with_framework_code(
    raw: str, unique_id: str, version: Version
) -> None:
    with pytest.raises(FrameError) as info:
        parse_frame(raw, version)
    err = info.value
    assert err.reply
    assert err.unique_id == unique_id
    assert err.code == framework_error_code(version)


@pytest.mark.parametrize(
    "raw",
    [
        '[3,"id"]',
        '[3,"id",{},{}]',
        '[3,"id","x"]',
        "[3,5,{}]",
        '[4,"id","C"]',
        '[4,"id","C","d",{},1]',
        '[4,"id",5,"d",{}]',
        '[4,"id","C",5,{}]',
        '[4,"id","C","d",[]]',
        '[4,5,"C","d",{}]',
    ],
)
def test_malformed_result_and_error_are_not_answered(raw: str) -> None:
    with pytest.raises(FrameError) as info:
        parse_frame(raw, Version.OCPP201)
    assert not info.value.reply
    assert info.value.message_type in (3, 4)


def test_unknown_message_type_by_version() -> None:
    with pytest.raises(FrameError) as info:
        parse_frame('[9,"id","A",{}]', Version.OCPP201)
    assert info.value.code == "MessageTypeNotSupported"
    assert info.value.reply
    assert info.value.unique_id == "id"
    with pytest.raises(FrameError) as info:
        parse_frame("[9,5]", Version.OCPP201)
    assert info.value.unique_id == "-1"
    for version in (Version.OCPP16, Version.OCPP21):
        with pytest.raises(FrameError) as info:
            parse_frame('[9,"id","A",{}]', version)
        assert not info.value.reply
        assert info.value.message_type == 9


def test_framework_codes() -> None:
    assert framework_error_code(Version.OCPP16) == "FormationViolation"
    assert framework_error_code(Version.OCPP201) == "RpcFrameworkError"
    assert framework_error_code(Version.OCPP21) == "RpcFrameworkError"


@pytest.mark.parametrize(
    "frame",
    [
        Call("1", "Heartbeat", {}),
        Call("1", "Echo", {"text": "héllo ✓"}),
        CallResult("2", {"a": [1, 2]}),
        CallErrorFrame("3", "InternalError", "oops", {"x": 1}),
        CallErrorFrame("3", "InternalError"),
    ],
)
def test_encode_round_trip(frame: Any) -> None:
    assert parse_frame(encode(frame), Version.OCPP201) == frame


def test_encode_is_compact_and_keeps_unicode() -> None:
    assert encode(Call("1", "A", {"t": "é"})) == '[2,"1","A",{"t":"é"}]'
    assert encode(CallErrorFrame("3", "C")) == '[4,"3","C","",{}]'


def test_encode_rejects_nan() -> None:
    with pytest.raises(ValueError, match="Out of range"):
        encode(CallResult("1", {"x": float("nan")}))
