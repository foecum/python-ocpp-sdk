"""Spec-text rules of OCPP 2.0.1 (beyond the JSON schemas) and the appendices constants."""

from typing import Any

import pytest

from ocpp_sdk.errors import CallError
from ocpp_sdk.v201 import appendices, new_registry
from ocpp_sdk.v201.iso15118 import GetCertificateStatusRequest

REGISTRY = new_registry()
NOW = "2025-03-14T09:26:53Z"
PERIOD = {"startPeriod": 0, "limit": 11.5}
SCHEDULE = {
    "id": 1,
    "chargingRateUnit": "A",
    "chargingSchedulePeriod": [PERIOD],
}
PROFILE = {
    "id": 1,
    "stackLevel": 0,
    "chargingProfilePurpose": "TxProfile",
    "chargingProfileKind": "Absolute",
    "chargingSchedule": [SCHEDULE],
}


def error(action: str, payload: dict[str, Any]) -> tuple[str, str]:
    with pytest.raises(CallError) as info:
        REGISTRY.decode_request(action, payload)
    return info.value.code, (info.value.details or {})["errors"][0]["field"]


def test_send_local_list_full_needs_id_token_info() -> None:
    entry = {"idToken": {"idToken": "T", "type": "Central"}}
    full = {"versionNumber": 1, "updateType": "Full", "localAuthorizationList": [entry]}
    assert error("SendLocalList", full) == (
        "OccurrenceConstraintViolation",
        "localAuthorizationList.0.idTokenInfo",
    )
    REGISTRY.decode_request("SendLocalList", {**full, "updateType": "Differential"})
    info = {"idTokenInfo": {"status": "Accepted"}}
    REGISTRY.decode_request(
        "SendLocalList", {**full, "localAuthorizationList": [{**entry, **info}]}
    )


def test_evse_ids_must_be_positive() -> None:
    assert (
        error(
            "RequestStartTransaction",
            {"idToken": {"idToken": "T", "type": "Central"}, "remoteStartId": 1, "evseId": 0},
        )[1]
        == "evseId"
    )
    assert (
        error(
            "NotifyChargingLimit", {"chargingLimit": {"chargingLimitSource": "EMS"}, "evseId": 0}
        )[1]
        == "evseId"
    )
    assert (
        error(
            "NotifyEVChargingSchedule", {"timeBase": NOW, "chargingSchedule": SCHEDULE, "evseId": 0}
        )[1]
        == "evseId"
    )


def test_remote_start_profile_must_be_tx_profile() -> None:
    request = {
        "idToken": {"idToken": "T", "type": "Central"},
        "remoteStartId": 1,
        "chargingProfile": {**PROFILE, "chargingProfilePurpose": "TxDefaultProfile"},
    }
    assert error("RequestStartTransaction", request) == (
        "PropertyConstraintViolation",
        "chargingProfile.chargingProfilePurpose",
    )
    REGISTRY.decode_request("RequestStartTransaction", {**request, "chargingProfile": PROFILE})


def test_transaction_id_only_with_tx_profile() -> None:
    bad = {
        "chargingProfile": {
            **PROFILE,
            "chargingProfilePurpose": "TxDefaultProfile",
            "transactionId": "T1",
        },
        "evseId": 1,
    }
    assert error("SetChargingProfile", bad) == (
        "PropertyConstraintViolation",
        "chargingProfile.transactionId",
    )
    ok = {"chargingProfile": {**PROFILE, "transactionId": "T1"}, "evseId": 1}
    REGISTRY.decode_request("SetChargingProfile", ok)


def test_charging_schedule_period_limits() -> None:
    def request(period: dict[str, Any]) -> dict[str, Any]:
        schedule = {**SCHEDULE, "chargingSchedulePeriod": [period]}
        return {"chargingProfile": {**PROFILE, "chargingSchedule": [schedule]}, "evseId": 1}

    for bad, field in (
        ({"limit": 8.25}, "limit"),
        ({"phaseToUse": 0}, "phaseToUse"),
        ({"phaseToUse": 4}, "phaseToUse"),
    ):
        code, path = error("SetChargingProfile", request({**PERIOD, **bad}))
        assert code == "PropertyConstraintViolation"
        assert path.endswith(f"chargingSchedulePeriod.0.{field}")
    REGISTRY.decode_request("SetChargingProfile", request({**PERIOD, "phaseToUse": 3}))


def test_variable_characteristics_values_list() -> None:
    def report(characteristics: dict[str, Any]) -> dict[str, Any]:
        data = {
            "component": {"name": "C"},
            "variable": {"name": "V"},
            "variableAttribute": [{}],
            "variableCharacteristics": characteristics,
        }
        return {"requestId": 1, "generatedAt": NOW, "seqNo": 0, "reportData": [data]}

    base = {"dataType": "OptionList", "supportsMonitoring": True}
    code, path = error("NotifyReport", report(base))
    assert (code, path.split(".")[-1]) == ("OccurrenceConstraintViolation", "valuesList")
    REGISTRY.decode_request("NotifyReport", report({**base, "valuesList": "A,B"}))
    REGISTRY.decode_request("NotifyReport", report({**base, "dataType": "boolean"}))


def test_publish_firmware_status_published_needs_location() -> None:
    assert error("PublishFirmwareStatusNotification", {"status": "Published"}) == (
        "OccurrenceConstraintViolation",
        "location",
    )
    REGISTRY.decode_request(
        "PublishFirmwareStatusNotification", {"status": "Published", "location": ["http://h/f"]}
    )
    REGISTRY.decode_request("PublishFirmwareStatusNotification", {"status": "Idle"})


def test_monitoring_severity_range() -> None:
    assert error("SetMonitoringLevel", {"severity": 10})[1] == "severity"
    assert error("SetMonitoringLevel", {"severity": -1})[1] == "severity"
    REGISTRY.decode_request("SetMonitoringLevel", {"severity": 9})


def test_custom_data_keeps_vendor_properties_and_other_extras_are_ignored() -> None:
    request = REGISTRY.decode_request(
        "Heartbeat", {"customData": {"vendorId": "v", "extra": [1, 2]}, "unknown": 1}
    )
    assert REGISTRY.encode(request) == {"customData": {"vendorId": "v", "extra": [1, 2]}}


def test_irregular_json_names_keep_the_spec_spelling() -> None:
    request = REGISTRY.decode_request(
        "GetCertificateStatus",
        {
            "ocspRequestData": {
                "hashAlgorithm": "SHA256",
                "issuerNameHash": "a",
                "issuerKeyHash": "b",
                "serialNumber": "1",
                "responderURL": "http://ocsp",
            }
        },
    )
    assert REGISTRY.encode(request)["ocspRequestData"]["responderURL"] == "http://ocsp"
    assert isinstance(request, GetCertificateStatusRequest)
    assert request.ocsp_request_data.responder_url == "http://ocsp"


def test_appendices() -> None:
    assert appendices.Component.AUTH_CTRLR == "AuthCtrlr"
    assert "AuthCtrlr" in appendices.COMPONENTS and len(appendices.VARIABLES) > 100
    assert appendices.Unit.KWH == "kWh" and appendices.Unit.A == "A"
    assert {u for u in appendices.UNITS} >= {"Wh", "kWh", "W", "kW", "Celsius"}
    assert all(r.group for r in appendices.REASON_CODES)
    assert appendices.is_known_security_event(appendices.SecurityEvent.STARTUP_OF_THE_DEVICE)
    assert not appendices.is_known_security_event("Nope")
    assert appendices.is_critical_security_event("StartupOfTheDevice")
    assert not appendices.is_critical_security_event("InvalidMessages")
    assert appendices.DEVICE_MODEL and appendices.DEVICE_MODEL[0].component == appendices.GENERIC
    assert any(e.required for e in appendices.DEVICE_MODEL)
