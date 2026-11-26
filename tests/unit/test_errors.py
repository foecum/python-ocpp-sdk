import pytest

from ocpp_sdk.errors import (
    V2_ERROR_CODES,
    V16_ERROR_CODES,
    CallError,
    OCPPError,
    ValidationError,
    code_for_version,
    error_codes,
)
from ocpp_sdk.versions import Version


def test_hierarchy() -> None:
    assert issubclass(CallError, OCPPError)
    assert issubclass(ValidationError, OCPPError)


def test_call_error_fields_and_str() -> None:
    err = CallError("NotSupported", "nope", {"a": 1})
    assert (err.code, err.description, err.details) == ("NotSupported", "nope", {"a": 1})
    assert str(err) == "NotSupported: nope"
    assert str(CallError("InternalError")) == "InternalError"
    assert CallError("X").details == {}


def test_validation_error_issues() -> None:
    err = ValidationError("bad", issues=[{"field": "a", "type": "missing"}])
    assert err.issues == [{"field": "a", "type": "missing"}]
    assert ValidationError("bad").issues == []


def test_spelling_differences() -> None:
    assert "FormationViolation" in V16_ERROR_CODES
    assert "OccurenceConstraintViolation" in V16_ERROR_CODES
    assert "FormatViolation" not in V16_ERROR_CODES
    assert "FormatViolation" in V2_ERROR_CODES
    assert "OccurrenceConstraintViolation" in V2_ERROR_CODES
    assert "FormationViolation" not in V2_ERROR_CODES
    assert "MessageTypeNotSupported" not in V16_ERROR_CODES
    assert "RpcFrameworkError" not in V16_ERROR_CODES


def test_error_codes_by_version() -> None:
    assert error_codes(Version.OCPP16) is V16_ERROR_CODES
    assert error_codes(Version.OCPP201) is V2_ERROR_CODES
    assert error_codes(Version.OCPP21) is V2_ERROR_CODES


@pytest.mark.parametrize(
    ("code", "version", "expected"),
    [
        ("FormatViolation", Version.OCPP16, "FormationViolation"),
        ("OccurrenceConstraintViolation", Version.OCPP16, "OccurenceConstraintViolation"),
        ("FormationViolation", Version.OCPP201, "FormatViolation"),
        ("OccurenceConstraintViolation", Version.OCPP21, "OccurrenceConstraintViolation"),
        ("NotSupported", Version.OCPP16, "NotSupported"),
        ("RpcFrameworkError", Version.OCPP16, "GenericError"),
        ("MessageTypeNotSupported", Version.OCPP16, "GenericError"),
        ("RpcFrameworkError", Version.OCPP201, "RpcFrameworkError"),
        ("Nonsense", Version.OCPP201, "GenericError"),
    ],
)
def test_code_for_version(code: str, version: Version, expected: str) -> None:
    assert code_for_version(code, version) == expected
