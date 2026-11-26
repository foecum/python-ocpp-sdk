"""Rules of the OCPP 1.6 security extension: PEM, hex, Base64, events and certificates."""

from typing import Any

import pytest

from ocpp_sdk.errors import CallError
from ocpp_sdk.transport.auth import check_authorization_key, generate_authorization_key
from ocpp_sdk.v16 import new_registry
from ocpp_sdk.v16.security import (
    SecurityEvent,
    SignCertificateRequest,
    is_critical_event,
    is_known_event,
)

REGISTRY = new_registry()
CERT = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
CSR = "-----BEGIN CERTIFICATE REQUEST-----\nMIIB\n-----END CERTIFICATE REQUEST-----"
HASH = {
    "hashAlgorithm": "SHA256",
    "issuerNameHash": "ab",
    "issuerKeyHash": "CD",
    "serialNumber": "f",
}


def rejected(action: str, payload: dict[str, Any]) -> tuple[str, str]:
    with pytest.raises(CallError) as info:
        REGISTRY.decode_request(action, payload)
    return info.value.code, (info.value.details or {})["errors"][0]["field"]


def accepted(action: str, payload: dict[str, Any]) -> None:
    REGISTRY.decode_request(action, payload)


@pytest.mark.parametrize(
    "csr",
    [
        CSR,
        CSR.replace("CERTIFICATE REQUEST", "NEW CERTIFICATE REQUEST"),
        f"\n{CSR}\n\n",
        CSR.replace("MIIB", "MI IB+/=\n=="),
    ],
)
def test_csr_accepts_pem(csr: str) -> None:
    accepted("SignCertificate", {"csr": csr})


@pytest.mark.parametrize(
    ("csr", "why"),
    [
        ("not pem", "must be PEM encoded"),
        (CERT, "unexpected PEM block"),
        (CSR + CSR, "at most 1"),
        (CSR + " trailing", "outside the PEM blocks"),
        (CSR.replace("MIIB", "MI!B"), "not Base64"),
        ("x" * 5501, "at most 5500"),
    ],
)
def test_csr_rejects(csr: str, why: str) -> None:
    code, field = rejected("SignCertificate", {"csr": csr})
    assert (code, field) in {
        ("PropertyConstraintViolation", "csr"),
        ("OccurenceConstraintViolation", "csr"),
    }
    with pytest.raises(CallError) as info:
        REGISTRY.decode_request("SignCertificate", {"csr": csr})
    assert why in info.value.description or "String should have at most" in info.value.description


def test_certificate_chain_may_hold_many_certificates_but_install_only_one() -> None:
    accepted("CertificateSigned", {"certificateChain": CERT + CERT + CERT})
    payload = {"certificateType": "CentralSystemRootCertificate", "certificate": CERT}
    accepted("InstallCertificate", payload)
    assert rejected("InstallCertificate", {**payload, "certificate": CERT + CERT}) == (
        "PropertyConstraintViolation",
        "certificate",
    )
    assert rejected("CertificateSigned", {"certificateChain": CSR})[1] == "certificateChain"


def test_certificate_hash_data() -> None:
    accepted("DeleteCertificate", {"certificateHashData": HASH})
    for bad, field in (
        ({"issuerNameHash": "abc"}, "issuerNameHash"),  # odd number of digits
        ({"issuerKeyHash": "zz"}, "issuerKeyHash"),
        ({"serialNumber": "0xFF"}, "serialNumber"),
        ({"hashAlgorithm": "MD5"}, "hashAlgorithm"),
    ):
        code, path = rejected("DeleteCertificate", {"certificateHashData": {**HASH, **bad}})
        assert (code, path) == ("PropertyConstraintViolation", f"certificateHashData.{field}")


def test_an_empty_installed_certificate_list_is_allowed() -> None:
    """The spec says 0..* where the schema says minItems 1; the spec wins."""
    for payload in ({"status": "NotFound"}, {"status": "NotFound", "certificateHashData": []}):
        REGISTRY.decode_response("GetInstalledCertificateIds", payload)


def test_signed_firmware_rules() -> None:
    firmware = {
        "location": "https://h/fw.bin",
        "retrieveDateTime": "2025-03-14T09:26:53Z",
        "signingCertificate": CERT,
        "signature": "c2lnbg==",
    }
    request = {"requestId": 1, "firmware": firmware}
    accepted("SignedUpdateFirmware", request)
    for change, field in (
        ({"signature": "not base64!"}, "firmware.signature"),
        ({"signature": "abc"}, "firmware.signature"),  # bad padding
        ({"location": "relative/path"}, "firmware.location"),
        ({"signingCertificate": CSR}, "firmware.signingCertificate"),
    ):
        assert rejected(
            "SignedUpdateFirmware", {**request, "firmware": {**firmware, **change}}
        ) == (
            "PropertyConstraintViolation",
            field,
        )
    assert rejected("SignedUpdateFirmware", {**request, "retries": -1})[1] == "retries"


def test_get_log_and_extended_trigger_rules() -> None:
    log = {"remoteLocation": "ftp://h/logs"}
    accepted("GetLog", {"log": log, "logType": "DiagnosticsLog", "requestId": 1})
    assert rejected(
        "GetLog", {"log": {"remoteLocation": "nope"}, "logType": "SecurityLog", "requestId": 1}
    )[1] == ("log.remoteLocation")
    assert rejected(
        "GetLog", {"log": log, "logType": "SecurityLog", "requestId": 1, "retryInterval": -5}
    )[1] == ("retryInterval")
    accepted("ExtendedTriggerMessage", {"requestedMessage": "Heartbeat"})
    assert (
        rejected("ExtendedTriggerMessage", {"requestedMessage": "Heartbeat", "connectorId": 0})[1]
        == "connectorId"
    )


def test_security_event_notification_type_is_an_open_string() -> None:
    for kind in ("StartupOfTheDevice", "VendorSpecificThing"):
        accepted("SecurityEventNotification", {"type": kind, "timestamp": "2025-01-01T00:00:00Z"})
    assert (
        rejected(
            "SecurityEventNotification", {"type": "x" * 51, "timestamp": "2025-01-01T00:00:00Z"}
        )[1]
        == "type"
    )


def test_event_helpers_follow_the_whitepaper_table() -> None:
    events = list(SecurityEvent)
    assert len(events) == 18
    assert all(is_known_event(e) for e in events)
    assert not is_known_event("VendorSpecificThing") and not is_critical_event(
        "VendorSpecificThing"
    )
    critical = {e.value for e in events if is_critical_event(e)}
    assert critical == {
        "FirmwareUpdated",
        "SettingSystemTime",
        "StartupOfTheDevice",
        "ResetOrReboot",
        "SecurityLogWasCleared",
        "MemoryExhaustion",
        "TamperDetectionActivated",
    }


def test_the_csr_model_reports_the_kind_of_error() -> None:
    with pytest.raises(ValueError, match="PEM"):
        SignCertificateRequest(csr="nope")


def test_authorization_key_helpers() -> None:
    assert check_authorization_key("0" * 32) and check_authorization_key("aB" * 20)
    for bad in ("", "0" * 30, "0" * 42, "0" * 33, "g" * 32, " " + "0" * 31):
        assert not check_authorization_key(bad)
    keys = {generate_authorization_key() for _ in range(5)}
    assert len(keys) == 5 and all(len(k) == 40 and check_authorization_key(k) for k in keys)
