"""OCPP 2.1 rules of the spec text and errata 2026-09 beyond the schemas, and the appendices."""

import copy
from pathlib import Path
from typing import Any

import pytest

from ocpp_sdk.errors import CallError
from ocpp_sdk.model import full_date_ok, time_of_day_ok
from ocpp_sdk.v21 import appendices, new_registry
from tests.schema import samples

SCHEMAS = Path(__file__).resolve().parents[2] / "docs" / "spec" / "2.1" / "schemas"
REGISTRY = new_registry()


def base(action: str) -> dict[str, Any]:
    _, payload = samples.load(SCHEMAS, f"{action}Request")
    assert isinstance(payload, dict)
    return payload


def error(action: str, payload: dict[str, Any]) -> tuple[str, str]:
    with pytest.raises(CallError) as info:
        REGISTRY.decode_request(action, payload)
    return info.value.code, (info.value.details or {})["errors"][0]["field"]


def profile_payload(**changes: Any) -> dict[str, Any]:
    payload = base("SetChargingProfile")
    payload["chargingProfile"].update(changes)
    return payload


def period(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = payload["chargingProfile"]["chargingSchedule"][0][
        "chargingSchedulePeriod"
    ][0]
    return result


def test_every_sample_is_accepted_including_the_rule_bearing_ones() -> None:
    for action in (
        "SetChargingProfile",
        "SetDERControl",
        "SetDefaultTariff",
        "NotifyPeriodicEventStream",
    ):
        schema_name = action if action == "NotifyPeriodicEventStream" else f"{action}Request"
        _, payload = samples.load(SCHEMAS, schema_name)
        REGISTRY.decode_request(action, payload)


def test_v2x_curves_need_two_coordinates_and_local_frequency_needs_its_curve() -> None:
    payload = base("SetChargingProfile")
    one = copy.deepcopy(payload)
    period(one)["v2xFreqWattCurve"] = period(one)["v2xFreqWattCurve"][:1]
    assert error("SetChargingProfile", one)[1].endswith("v2xFreqWattCurve")
    sig = copy.deepcopy(payload)
    period(sig)["v2xSignalWattCurve"] = period(sig)["v2xSignalWattCurve"][:1]
    assert error("SetChargingProfile", sig)[1].endswith("v2xSignalWattCurve")
    local = copy.deepcopy(payload)
    period(local)["operationMode"] = "LocalFrequency"
    del period(local)["v2xFreqWattCurve"]
    assert error("SetChargingProfile", local) == (
        "OccurrenceConstraintViolation",
        "chargingProfile.chargingSchedule.0.chargingSchedulePeriod.0.v2xFreqWattCurve",
    )
    other = copy.deepcopy(payload)
    del period(other)["v2xFreqWattCurve"]
    period(other)["operationMode"] = "ChargingOnly"
    REGISTRY.decode_request("SetChargingProfile", other)


def test_randomized_delay_only_for_tx_profiles_and_limit_has_one_decimal() -> None:
    payload = profile_payload(chargingProfilePurpose="ChargingStationMaxProfile")
    del payload["chargingProfile"]["transactionId"]
    payload["chargingProfile"]["chargingSchedule"][0]["randomizedDelay"] = 30
    assert error("SetChargingProfile", payload)[1].endswith("randomizedDelay")
    payload["chargingProfile"]["chargingSchedule"][0]["randomizedDelay"] = 0
    REGISTRY.decode_request("SetChargingProfile", payload)
    decimals = base("SetChargingProfile")
    period(decimals)["limit"] = 8.25
    assert error("SetChargingProfile", decimals)[1].endswith("chargingSchedulePeriod.0.limit")
    del period(decimals)["limit"]  # optional in 2.1: a setpoint may replace it
    REGISTRY.decode_request("SetChargingProfile", decimals)


def test_limit_max_discharge_needs_a_percentage_between_0_and_100() -> None:
    payload = base("SetDERControl")
    limit = payload["limitMaxDischarge"]
    assert limit["pctMaxDischargePower"] is not None
    for bad in (101, -1):
        broken = copy.deepcopy(payload)
        broken["limitMaxDischarge"]["pctMaxDischargePower"] = bad
        assert error("SetDERControl", broken)[1].endswith("pctMaxDischargePower")
    gone = copy.deepcopy(payload)
    del gone["limitMaxDischarge"]["pctMaxDischargePower"]
    assert error("SetDERControl", gone)[0] == "OccurrenceConstraintViolation"


@pytest.mark.parametrize(
    "action", ["SetDERControl", "GetDERControl", "ClearDERControl", "NotifyDERAlarm"]
)
def test_power_monitoring_must_trip_is_not_a_standalone_control(action: str) -> None:
    payload = base(action)
    REGISTRY.decode_request(action, payload)
    payload["controlType"] = "PowerMonitoringMustTrip"
    assert error(action, payload) == ("PropertyConstraintViolation", "controlType")


def test_hv10_voltage_parameters_go_together() -> None:
    payload = base("SetDERControl")
    assert "voltageParams" in payload["curve"]
    for drop in ("hv10MinMeanValue", "hv10MinMeanTripDelay"):
        broken = copy.deepcopy(payload)
        del broken["curve"]["voltageParams"][drop]
        assert error("SetDERControl", broken)[0] == "OccurrenceConstraintViolation"


def test_tariff_conditions_use_24h_times_and_full_dates() -> None:
    payload = base("SetDefaultTariff")
    conditions = payload["tariff"]["energy"]["prices"][0]["conditions"]
    for field, bad in (
        ("startTimeOfDay", "7:30"),
        ("endTimeOfDay", "24:00"),
        ("validFromDate", "2025-02-30"),
        ("validToDate", "01.02.2025"),
    ):
        broken = copy.deepcopy(payload)
        broken["tariff"]["energy"]["prices"][0]["conditions"][field] = bad
        code, path = error("SetDefaultTariff", broken)
        assert code == "PropertyConstraintViolation" and path.endswith(f"conditions.{field}")
    assert conditions["startTimeOfDay"] == "07:30"
    REGISTRY.decode_request("SetDefaultTariff", payload)


def test_carried_over_2_0_1_rules_still_apply() -> None:
    start = base("RequestStartTransaction")
    start["evseId"] = 0
    assert error("RequestStartTransaction", start)[1] == "evseId"
    mon = {"severity": 10}
    assert error("SetMonitoringLevel", mon)[1] == "severity"
    local = base("SendLocalList")
    local["updateType"] = "Full"
    del local["localAuthorizationList"][0]["idTokenInfo"]
    assert error("SendLocalList", local)[0] == "OccurrenceConstraintViolation"


def test_helpers() -> None:
    assert time_of_day_ok("00:00") and time_of_day_ok("23:59")
    assert (
        not time_of_day_ok("7:30")
        and not time_of_day_ok("12:60")
        and not time_of_day_ok("07:30:00")
    )
    assert (
        full_date_ok("2024-02-29")
        and not full_date_ok("2025-02-29")
        and not full_date_ok("2025-2-1")
    )


def test_appendices_of_2_1() -> None:
    assert "AuthCtrlr" in appendices.COMPONENTS and "BatterySwapCtrlr" in appendices.COMPONENTS
    assert appendices.IdTokenType.CENTRAL == "Central" and "eMAID" in appendices.ID_TOKEN_TYPES
    assert (
        appendices.ChargingLimitSource.EMS == "EMS" and len(appendices.CHARGING_LIMIT_SOURCES) == 4
    )
    assert len(appendices.CONNECTOR_TYPES) > 20 and len(appendices.PAYMENT_BRANDS) > 10
    assert "ECDSA-secp256k1-SHA256" in appendices.SIGNING_METHODS
    assert appendices.AdditionalInfoType.EVCCID == "EVCCID"
    assert appendices.AdditionalInfoAdHocType.PSP_REF == "PspRef"
    assert appendices.PaymentRecognition.CC == "CC"
    assert appendices.is_known_security_event("StartupOfTheDevice")


def containers(node: Any, key: str, path: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """The paths of every dict below ``node`` that has ``key``."""
    found: list[tuple[Any, ...]] = []
    if isinstance(node, dict):
        if key in node:
            found.append(path)
        for k, v in node.items():
            found += containers(v, key, (*path, k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += containers(v, key, (*path, i))
    return found


def at(payload: Any, path: tuple[Any, ...]) -> Any:
    for step in path:
        payload = payload[step]
    return payload


def test_time_and_date_rules_apply_to_every_tariff_condition_type() -> None:
    payload = base("SetDefaultTariff")
    places = containers(payload, "startTimeOfDay")
    assert len(places) >= 2  # TariffConditions and TariffConditionsFixed
    for place in places:
        for field, bad in (("endTimeOfDay", "9pm"), ("validToDate", "2025/12/31")):
            broken = copy.deepcopy(payload)
            at(broken, place)[field] = bad
            assert error("SetDefaultTariff", broken)[1].endswith(field)


def test_the_remaining_2_0_1_rules_in_2_1() -> None:
    values = base("NotifyReport")
    places = containers(values, "dataType")
    assert places
    for place in places:
        broken = copy.deepcopy(values)
        node = at(broken, place)
        node["dataType"] = "OptionList"
        node.pop("valuesList", None)
        assert error("NotifyReport", broken)[1].endswith("valuesList")

    firmware = {"status": "Published", "location": ["http://h/f"]}
    REGISTRY.decode_request("PublishFirmwareStatusNotification", firmware)
    assert error("PublishFirmwareStatusNotification", {"status": "Published"})[1] == "location"

    local = base("SendLocalList")
    local["updateType"] = "Full"
    assert any(  # a Full update with idTokenInfo everywhere is fine
        REGISTRY.decode_request("SendLocalList", local) for _ in (0,)
    )

    start = base("RequestStartTransaction")
    start["chargingProfile"]["chargingProfilePurpose"] = "TxDefaultProfile"
    start["chargingProfile"].pop("transactionId", None)
    assert error("RequestStartTransaction", start)[1] == "chargingProfile.chargingProfilePurpose"

    profile = base("SetChargingProfile")
    profile["chargingProfile"]["chargingProfilePurpose"] = "TxDefaultProfile"
    profile["chargingProfile"]["transactionId"] = "T-1"
    assert error("SetChargingProfile", profile)[1] == "chargingProfile.transactionId"
