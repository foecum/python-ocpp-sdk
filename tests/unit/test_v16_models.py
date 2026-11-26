"""Spec-text rules and constraints of the generated OCPP 1.6 models."""

from typing import Any

import pytest

from ocpp_sdk.errors import CallError, ValidationError
from ocpp_sdk.v16 import new_registry
from ocpp_sdk.v16.core import BootNotificationConfirmation, MeterValuesRequest
from ocpp_sdk.v16.localauth import SendLocalListRequest
from ocpp_sdk.v16.types import UnitOfMeasure

REGISTRY = new_registry()
NOW = "2025-01-02T03:04:05Z"

PERIOD = {"startPeriod": 0, "limit": 11.5}
SCHEDULE = {"chargingRateUnit": "A", "chargingSchedulePeriod": [PERIOD]}
PROFILE = {
    "chargingProfileId": 1,
    "stackLevel": 0,
    "chargingProfilePurpose": "TxProfile",
    "chargingProfileKind": "Absolute",
    "chargingSchedule": SCHEDULE,
}
SAMPLED = {"value": "12"}


def with_(base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {**base, **changes}


def request_error(action: str, payload: dict[str, Any]) -> CallError:
    with pytest.raises(CallError) as info:
        REGISTRY.decode_request(action, payload)
    return info.value


def test_registry_has_the_39_messages() -> None:
    assert len(REGISTRY.actions()) == 39
    assert getattr(REGISTRY.request_type("Heartbeat"), "ACTION", None) == "Heartbeat"


VALID: list[tuple[str, dict[str, Any]]] = [
    ("BootNotification", {"chargePointVendor": "V", "chargePointModel": "M", "imsi": ""}),
    ("ChangeConfiguration", {"key": "HeartbeatInterval", "value": ""}),  # empty value is allowed
    ("ChangeAvailability", {"connectorId": 0, "type": "Inoperative"}),
    (
        "MeterValues",
        {"connectorId": 0, "meterValue": [{"timestamp": NOW, "sampledValue": [SAMPLED]}]},
    ),
    ("RemoteStartTransaction", {"idTag": "T", "connectorId": 1, "chargingProfile": PROFILE}),
    ("StartTransaction", {"connectorId": 1, "idTag": "T", "meterStart": 0, "timestamp": NOW}),
    ("GetDiagnostics", {"location": "ftp://host/dir", "retries": 0, "retryInterval": 0}),
    ("UpdateFirmware", {"location": "https://h/fw.bin", "retrieveDate": NOW}),
    ("SetChargingProfile", {"connectorId": 0, "csChargingProfiles": PROFILE}),
    ("ClearChargingProfile", {"connectorId": 0, "stackLevel": 0}),
    ("GetCompositeSchedule", {"connectorId": 0, "duration": 0}),
    ("TriggerMessage", {"requestedMessage": "Heartbeat", "connectorId": 1}),
    ("ReserveNow", {"connectorId": 0, "expiryDate": NOW, "idTag": "T", "reservationId": 7}),
    (
        "SendLocalList",
        {
            "listVersion": 1,
            "updateType": "Differential",
            "localAuthorizationList": [{"idTag": "A"}, {"idTag": "B"}],
        },
    ),
    (
        "SendLocalList",
        {
            "listVersion": 1,
            "updateType": "Full",
            "localAuthorizationList": [{"idTag": "A", "idTagInfo": {"status": "Accepted"}}],
        },
    ),
]


@pytest.mark.parametrize(("action", "payload"), VALID)
def test_valid_requests_decode(action: str, payload: dict[str, Any]) -> None:
    assert type(REGISTRY.decode_request(action, payload)).__name__ == f"{action}Request"


INVALID: list[tuple[str, dict[str, Any], str, str]] = [
    # (action, payload, CALLERROR code, field path); 1.6 spells Occurence with one r
    (
        "BootNotification",
        {"chargePointVendor": "V"},
        "OccurenceConstraintViolation",
        "chargePointModel",
    ),
    (
        "BootNotification",
        {"chargePointVendor": "", "chargePointModel": "M"},
        "PropertyConstraintViolation",
        "chargePointVendor",
    ),
    (
        "BootNotification",
        {"chargePointVendor": "V" * 21, "chargePointModel": "M"},
        "PropertyConstraintViolation",
        "chargePointVendor",
    ),
    (
        "BootNotification",
        {"chargePointVendor": 5, "chargePointModel": "M"},
        "TypeConstraintViolation",
        "chargePointVendor",
    ),
    ("ChangeConfiguration", {"key": "", "value": "x"}, "PropertyConstraintViolation", "key"),
    (
        "ChangeAvailability",
        {"connectorId": -1, "type": "Operative"},
        "PropertyConstraintViolation",
        "connectorId",
    ),
    (
        "ChangeAvailability",
        {"connectorId": 1.0, "type": "Operative"},
        "TypeConstraintViolation",
        "connectorId",
    ),
    (
        "ChangeAvailability",
        {"connectorId": True, "type": "Operative"},
        "TypeConstraintViolation",
        "connectorId",
    ),
    (
        "ChangeAvailability",
        {"connectorId": 1, "type": "Gone"},
        "PropertyConstraintViolation",
        "type",
    ),
    (
        "StartTransaction",
        {"connectorId": 0, "idTag": "T", "meterStart": 0, "timestamp": NOW},
        "PropertyConstraintViolation",
        "connectorId",
    ),
    (
        "StartTransaction",
        {"connectorId": 1, "idTag": "T", "meterStart": 0, "timestamp": "soon"},
        "PropertyConstraintViolation",
        "timestamp",
    ),
    ("UnlockConnector", {"connectorId": 0}, "PropertyConstraintViolation", "connectorId"),
    (
        "TriggerMessage",
        {"requestedMessage": "Heartbeat", "connectorId": 0},
        "PropertyConstraintViolation",
        "connectorId",
    ),
    (
        "RemoteStartTransaction",
        {"idTag": "T", "connectorId": 0},
        "PropertyConstraintViolation",
        "connectorId",
    ),
    (
        "MeterValues",
        {"connectorId": 0, "meterValue": []},
        "OccurenceConstraintViolation",
        "meterValue",
    ),
    (
        "MeterValues",
        {"connectorId": 0, "meterValue": [{"timestamp": NOW, "sampledValue": []}]},
        "OccurenceConstraintViolation",
        "meterValue.0.sampledValue",
    ),
    (
        "MeterValues",
        {"connectorId": 0, "meterValue": [{"timestamp": NOW, "sampledValue": [{"value": ""}]}]},
        "PropertyConstraintViolation",
        "meterValue.0.sampledValue.0.value",
    ),
    ("GetDiagnostics", {"location": "not-a-uri"}, "PropertyConstraintViolation", "location"),
    ("UpdateFirmware", {"location": "ftp://h/f"}, "OccurenceConstraintViolation", "retrieveDate"),
    (
        "UpdateFirmware",
        {"location": "ftp://h/f", "retrieveDate": NOW, "retries": -1},
        "PropertyConstraintViolation",
        "retries",
    ),
    (
        "GetCompositeSchedule",
        {"connectorId": 0, "duration": -1},
        "PropertyConstraintViolation",
        "duration",
    ),
    ("ClearChargingProfile", {"stackLevel": -1}, "PropertyConstraintViolation", "stackLevel"),
    (
        "ReserveNow",
        {"connectorId": -1, "expiryDate": NOW, "idTag": "T", "reservationId": 1},
        "PropertyConstraintViolation",
        "connectorId",
    ),
    # spec-text rules
    (
        "SetChargingProfile",
        {
            "connectorId": 0,
            "csChargingProfiles": with_(
                PROFILE,
                chargingSchedule=with_(
                    SCHEDULE, chargingSchedulePeriod=[{"startPeriod": 60, "limit": 8}]
                ),
            ),
        },
        "PropertyConstraintViolation",
        "csChargingProfiles.chargingSchedule.chargingSchedulePeriod.0.startPeriod",
    ),
    (
        "SetChargingProfile",
        {
            "connectorId": 0,
            "csChargingProfiles": with_(
                PROFILE, chargingSchedule=with_(SCHEDULE, chargingSchedulePeriod=[])
            ),
        },
        "OccurenceConstraintViolation",
        "csChargingProfiles.chargingSchedule.chargingSchedulePeriod",
    ),
    (
        "SetChargingProfile",
        {
            "connectorId": 0,
            "csChargingProfiles": with_(
                PROFILE,
                chargingSchedule=with_(
                    SCHEDULE, chargingSchedulePeriod=[{"startPeriod": 0, "limit": 8.25}]
                ),
            ),
        },
        "PropertyConstraintViolation",
        "csChargingProfiles.chargingSchedule.chargingSchedulePeriod.0.limit",
    ),
    (
        "SetChargingProfile",
        {
            "connectorId": 0,
            "csChargingProfiles": with_(
                PROFILE, chargingSchedule=with_(SCHEDULE, minChargingRate=6.05)
            ),
        },
        "PropertyConstraintViolation",
        "csChargingProfiles.chargingSchedule.minChargingRate",
    ),
    (
        "SetChargingProfile",
        {
            "connectorId": 0,
            "csChargingProfiles": with_(
                PROFILE,
                chargingSchedule=with_(
                    SCHEDULE,
                    chargingSchedulePeriod=[{"startPeriod": 0, "limit": 8, "numberPhases": 0}],
                ),
            ),
        },
        "PropertyConstraintViolation",
        "csChargingProfiles.chargingSchedule.chargingSchedulePeriod.0.numberPhases",
    ),
    (
        "SetChargingProfile",
        {"connectorId": 0, "csChargingProfiles": with_(PROFILE, stackLevel=-1)},
        "PropertyConstraintViolation",
        "csChargingProfiles.stackLevel",
    ),
    (
        "RemoteStartTransaction",
        {
            "idTag": "T",
            "chargingProfile": with_(PROFILE, chargingProfilePurpose="TxDefaultProfile"),
        },
        "PropertyConstraintViolation",
        "chargingProfile.chargingProfilePurpose",
    ),
    (
        "SendLocalList",
        {
            "listVersion": 1,
            "updateType": "Differential",
            "localAuthorizationList": [{"idTag": "Abc"}, {"idTag": "x"}, {"idTag": "aBC"}],
        },
        "PropertyConstraintViolation",
        "localAuthorizationList.2.idTag",
    ),
    (
        "SendLocalList",
        {
            "listVersion": 1,
            "updateType": "Full",
            "localAuthorizationList": [
                {"idTag": "A", "idTagInfo": {"status": "Accepted"}},
                {"idTag": "B"},
            ],
        },
        "OccurenceConstraintViolation",
        "localAuthorizationList.1.idTagInfo",
    ),
]


@pytest.mark.parametrize(("action", "payload", "code", "field"), INVALID)
def test_invalid_requests(action: str, payload: dict[str, Any], code: str, field: str) -> None:
    error = request_error(action, payload)
    assert (error.code, (error.details or {})["errors"][0]["field"]) == (code, field)
    assert error.description.startswith(f"{field}: ")


def test_sampled_value_units_accept_both_spellings_of_celsius() -> None:
    for unit in ("Celcius", "Celsius"):
        payload = {
            "connectorId": 1,
            "meterValue": [{"timestamp": NOW, "sampledValue": [{"value": "21", "unit": unit}]}],
        }
        request = REGISTRY.decode_request("MeterValues", payload)
        assert isinstance(request, MeterValuesRequest)
        assert request.meter_value[0].sampled_value[0].unit == UnitOfMeasure(unit)


def test_unknown_properties_are_ignored() -> None:
    request = REGISTRY.decode_request("Authorize", {"idTag": "T", "extra": {"a": 1}})
    assert REGISTRY.encode(request) == {"idTag": "T"}


def test_response_decoding_and_encoding() -> None:
    response = REGISTRY.decode_response(
        "BootNotification",
        {"status": "Accepted", "currentTime": "2025-01-02T04:04:05+01:00", "interval": 300},
    )
    assert isinstance(response, BootNotificationConfirmation)
    assert REGISTRY.encode(response) == {"status": "Accepted", "currentTime": NOW, "interval": 300}


def test_invalid_response_is_reported() -> None:
    with pytest.raises(ValidationError) as info:
        REGISTRY.decode_response("GetLocalListVersion", {"listVersion": -2})
    assert info.value.issues == [{"field": "listVersion", "type": "greater_than_equal"}]
    assert REGISTRY.decode_response("GetLocalListVersion", {"listVersion": -1})


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_encode_rejects_a_model_broken_after_creation() -> None:
    request = REGISTRY.decode_request("SendLocalList", {"listVersion": 1, "updateType": "Full"})
    assert isinstance(request, SendLocalListRequest)
    request.update_type = "Differential"  # type: ignore[assignment]
    assert REGISTRY.encode(request) == {"listVersion": 1, "updateType": "Differential"}
    request.list_version = "x"  # type: ignore[assignment]
    with pytest.raises(ValidationError):
        REGISTRY.encode(request)
