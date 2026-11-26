"""Tables that drive the generator: modules, names, constraints and spec-text rules.

Everything the JSON schemas do not say lives here. Names follow the spelling of
the specification so users can search the spec; the choices match go-ocpp-sdk.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Module:
    """One generated message module (an OCPP 1.6 feature profile)."""

    name: str
    title: str
    messages: tuple[str, ...]


@dataclass(frozen=True)
class Named:
    """A shared type or enum: its docstring and the schema locations it covers.

    A location is ``<schema file stem>.<json path>`` where array items are written
    ``[]`` (``MeterValues.meterValue[].sampledValue[]``).
    """

    doc: str
    locations: tuple[str, ...]


@dataclass(frozen=True)
class Profile:
    """Everything the generator needs to know about one OCPP version."""

    version: str
    package: str
    schema_dir: str
    request_suffix: str
    response_suffix: str
    modules: tuple[Module, ...]
    descriptions: dict[str, str]
    enums: dict[str, Named]
    types: dict[str, Named]
    #: ``Model.wireName`` -> minimum for an integer field (``ge``).
    int_min: dict[str, int] = field(default_factory=dict)
    #: ``Model.wireName`` -> minimum number of items of an array.
    array_min: dict[str, int] = field(default_factory=dict)
    #: required strings that may be empty (``Model.wireName``).
    empty_allowed: frozenset[str] = frozenset()
    #: ``Model`` -> Python statements of the spec-text rules (see ``rules``).
    rules: dict[str, str] = field(default_factory=dict)
    #: enum values -> member names where the generic conversion is ugly.
    member_names: dict[str, str] = field(default_factory=dict)
    #: ``wireName`` -> value used for an integer in generated doctest samples.
    sample_ints: dict[str, int] = field(default_factory=dict)
    #: messages with a schema that a later roadmap item generates.
    deferred: frozenset[str] = frozenset()


def _loc(*parts: str) -> tuple[str, ...]:
    return parts


_MODULES_V16 = (
    Module(
        "core",
        "Core",
        (
            "Authorize",
            "BootNotification",
            "ChangeAvailability",
            "ChangeConfiguration",
            "ClearCache",
            "DataTransfer",
            "GetConfiguration",
            "Heartbeat",
            "MeterValues",
            "RemoteStartTransaction",
            "RemoteStopTransaction",
            "Reset",
            "StartTransaction",
            "StatusNotification",
            "StopTransaction",
            "UnlockConnector",
        ),
    ),
    Module(
        "firmware",
        "Firmware Management",
        (
            "DiagnosticsStatusNotification",
            "FirmwareStatusNotification",
            "GetDiagnostics",
            "UpdateFirmware",
        ),
    ),
    Module("localauth", "Local Auth List Management", ("GetLocalListVersion", "SendLocalList")),
    Module("reservation", "Reservation", ("CancelReservation", "ReserveNow")),
    Module(
        "smartcharging",
        "Smart Charging",
        ("ClearChargingProfile", "GetCompositeSchedule", "SetChargingProfile"),
    ),
    Module("remotetrigger", "Remote Trigger", ("TriggerMessage",)),
)

_DESCRIPTIONS_V16 = {
    "Authorize": "Asks the Central System whether an identifier may charge.",
    "BootNotification": "Registers a Charge Point with the Central System after it starts up.",
    "ChangeAvailability": "Asks the Charge Point to make a connector (or itself) operative or not.",
    "ChangeConfiguration": "Asks the Charge Point to change one configuration key.",
    "ClearCache": "Asks the Charge Point to clear its authorization cache.",
    "DataTransfer": "Carries vendor-specific data in either direction.",
    "GetConfiguration": "Asks the Charge Point for its configuration keys.",
    "Heartbeat": "Tells the Central System that the Charge Point is alive.",
    "MeterValues": "Reports meter values sampled at a connector.",
    "RemoteStartTransaction": "Asks the Charge Point to start a transaction for an identifier.",
    "RemoteStopTransaction": "Asks the Charge Point to stop a running transaction.",
    "Reset": "Asks the Charge Point to reset itself.",
    "StartTransaction": "Tells the Central System that a transaction has started.",
    "StatusNotification": "Reports a status or error change of a connector.",
    "StopTransaction": "Tells the Central System that a transaction has ended.",
    "UnlockConnector": "Asks the Charge Point to unlock a connector.",
    "DiagnosticsStatusNotification": "Reports the progress of a diagnostics upload.",
    "FirmwareStatusNotification": "Reports the progress of a firmware update.",
    "GetDiagnostics": "Asks the Charge Point to upload its diagnostics to a location.",
    "UpdateFirmware": "Asks the Charge Point to download and install firmware.",
    "GetLocalListVersion": "Asks the Charge Point for the version of its local authorization list.",
    "SendLocalList": "Sends a full or differential local authorization list.",
    "CancelReservation": "Cancels a reservation.",
    "ReserveNow": "Reserves a connector for an identifier.",
    "ClearChargingProfile": "Clears the charging profiles that match the given criteria.",
    "GetCompositeSchedule": "Asks for the schedule that results from all charging profiles.",
    "SetChargingProfile": "Installs a charging profile.",
    "TriggerMessage": "Asks the Charge Point to send a message of the given kind.",
}

_ENUMS_V16 = {
    "AuthorizationStatus": Named(
        "Whether an identifier is authorized.",
        _loc(
            "AuthorizeResponse.idTagInfo.status",
            "SendLocalList.localAuthorizationList[].idTagInfo.status",
            "StartTransactionResponse.idTagInfo.status",
            "StopTransactionResponse.idTagInfo.status",
        ),
    ),
    "RegistrationStatus": Named(
        "Whether the Charge Point was accepted by BootNotification.",
        _loc("BootNotificationResponse.status"),
    ),
    "AvailabilityType": Named(
        "The availability a ChangeAvailability asks for.", _loc("ChangeAvailability.type")
    ),
    "AvailabilityStatus": Named(
        "The answer to ChangeAvailability.", _loc("ChangeAvailabilityResponse.status")
    ),
    "ConfigurationStatus": Named(
        "The answer to ChangeConfiguration.", _loc("ChangeConfigurationResponse.status")
    ),
    "ClearCacheStatus": Named("The answer to ClearCache.", _loc("ClearCacheResponse.status")),
    "DataTransferStatus": Named("The answer to DataTransfer.", _loc("DataTransferResponse.status")),
    "RemoteStartStopStatus": Named(
        "The answer to RemoteStartTransaction and RemoteStopTransaction.",
        _loc("RemoteStartTransactionResponse.status", "RemoteStopTransactionResponse.status"),
    ),
    "ResetType": Named("The kind of reset to perform.", _loc("Reset.type")),
    "ResetStatus": Named("The answer to Reset.", _loc("ResetResponse.status")),
    "UnlockStatus": Named("The answer to UnlockConnector.", _loc("UnlockConnectorResponse.status")),
    "ChargePointErrorCode": Named(
        "The error a connector reports in StatusNotification.", _loc("StatusNotification.errorCode")
    ),
    "ChargePointStatus": Named(
        "The status a connector reports in StatusNotification.", _loc("StatusNotification.status")
    ),
    "Reason": Named("Why a transaction was stopped.", _loc("StopTransaction.reason")),
    "ReadingContext": Named(
        "The reason a meter value was taken.",
        _loc(
            "MeterValues.meterValue[].sampledValue[].context",
            "StopTransaction.transactionData[].sampledValue[].context",
        ),
    ),
    "ValueFormat": Named(
        "Whether a sampled value is raw data or signed data.",
        _loc(
            "MeterValues.meterValue[].sampledValue[].format",
            "StopTransaction.transactionData[].sampledValue[].format",
        ),
    ),
    "Measurand": Named(
        "The quantity a sampled value measures.",
        _loc(
            "MeterValues.meterValue[].sampledValue[].measurand",
            "StopTransaction.transactionData[].sampledValue[].measurand",
        ),
    ),
    "Phase": Named(
        "The phase a sampled value applies to.",
        _loc(
            "MeterValues.meterValue[].sampledValue[].phase",
            "StopTransaction.transactionData[].sampledValue[].phase",
        ),
    ),
    "Location": Named(
        "Where a sampled value was measured.",
        _loc(
            "MeterValues.meterValue[].sampledValue[].location",
            "StopTransaction.transactionData[].sampledValue[].location",
        ),
    ),
    "UnitOfMeasure": Named(
        "The unit of a sampled value. ``Celcius`` (sic) and ``Celsius`` are both valid.",
        _loc(
            "MeterValues.meterValue[].sampledValue[].unit",
            "StopTransaction.transactionData[].sampledValue[].unit",
        ),
    ),
    "ChargingProfilePurposeType": Named(
        "What a charging profile is for.",
        _loc(
            "ClearChargingProfile.chargingProfilePurpose",
            "RemoteStartTransaction.chargingProfile.chargingProfilePurpose",
            "SetChargingProfile.csChargingProfiles.chargingProfilePurpose",
        ),
    ),
    "ChargingProfileKindType": Named(
        "Whether a charging schedule is absolute, recurring or relative.",
        _loc(
            "RemoteStartTransaction.chargingProfile.chargingProfileKind",
            "SetChargingProfile.csChargingProfiles.chargingProfileKind",
        ),
    ),
    "RecurrencyKindType": Named(
        "How often a recurring charging profile repeats.",
        _loc(
            "RemoteStartTransaction.chargingProfile.recurrencyKind",
            "SetChargingProfile.csChargingProfiles.recurrencyKind",
        ),
    ),
    "ChargingRateUnitType": Named(
        "The unit of the limits of a charging schedule: amperes or watts.",
        _loc(
            "GetCompositeSchedule.chargingRateUnit",
            "GetCompositeScheduleResponse.chargingSchedule.chargingRateUnit",
            "RemoteStartTransaction.chargingProfile.chargingSchedule.chargingRateUnit",
            "SetChargingProfile.csChargingProfiles.chargingSchedule.chargingRateUnit",
        ),
    ),
    "DiagnosticsStatus": Named(
        "The progress of a diagnostics upload.", _loc("DiagnosticsStatusNotification.status")
    ),
    "FirmwareStatus": Named(
        "The progress of a firmware update.", _loc("FirmwareStatusNotification.status")
    ),
    "UpdateType": Named(
        "Whether a local authorization list update is full or differential.",
        _loc("SendLocalList.updateType"),
    ),
    "UpdateStatus": Named("The answer to SendLocalList.", _loc("SendLocalListResponse.status")),
    "ReservationStatus": Named("The answer to ReserveNow.", _loc("ReserveNowResponse.status")),
    "CancelReservationStatus": Named(
        "The answer to CancelReservation.", _loc("CancelReservationResponse.status")
    ),
    "ChargingProfileStatus": Named(
        "The answer to SetChargingProfile.", _loc("SetChargingProfileResponse.status")
    ),
    "ClearChargingProfileStatus": Named(
        "The answer to ClearChargingProfile.", _loc("ClearChargingProfileResponse.status")
    ),
    "GetCompositeScheduleStatus": Named(
        "The answer to GetCompositeSchedule.", _loc("GetCompositeScheduleResponse.status")
    ),
    "MessageTrigger": Named(
        "The message a TriggerMessage asks for.", _loc("TriggerMessage.requestedMessage")
    ),
    "TriggerMessageStatus": Named(
        "The answer to TriggerMessage.", _loc("TriggerMessageResponse.status")
    ),
}

_TYPES_V16 = {
    "IdTagInfo": Named(
        "Whether an identifier (idTag) is authorized.",
        _loc(
            "AuthorizeResponse.idTagInfo",
            "SendLocalList.localAuthorizationList[].idTagInfo",
            "StartTransactionResponse.idTagInfo",
            "StopTransactionResponse.idTagInfo",
        ),
    ),
    "SampledValue": Named(
        "One measured value of a MeterValue.",
        _loc(
            "MeterValues.meterValue[].sampledValue[]",
            "StopTransaction.transactionData[].sampledValue[]",
        ),
    ),
    "MeterValue": Named(
        "Sampled values taken at the same moment.",
        _loc("MeterValues.meterValue[]", "StopTransaction.transactionData[]"),
    ),
    "KeyValue": Named(
        "One configuration key of a GetConfiguration answer.",
        _loc("GetConfigurationResponse.configurationKey[]"),
    ),
    "ChargingSchedulePeriod": Named(
        "One period of a charging schedule.",
        _loc(
            "GetCompositeScheduleResponse.chargingSchedule.chargingSchedulePeriod[]",
            "RemoteStartTransaction.chargingProfile.chargingSchedule.chargingSchedulePeriod[]",
            "SetChargingProfile.csChargingProfiles.chargingSchedule.chargingSchedulePeriod[]",
        ),
    ),
    "ChargingSchedule": Named(
        "Charging limits over time.",
        _loc(
            "GetCompositeScheduleResponse.chargingSchedule",
            "RemoteStartTransaction.chargingProfile.chargingSchedule",
            "SetChargingProfile.csChargingProfiles.chargingSchedule",
        ),
    ),
    "ChargingProfile": Named(
        "A charging schedule with the rules for when it applies.",
        _loc(
            "RemoteStartTransaction.chargingProfile",
            "SetChargingProfile.csChargingProfiles",
        ),
    ),
    "AuthorizationData": Named(
        "One entry of a local authorization list update.",
        _loc("SendLocalList.localAuthorizationList[]"),
    ),
}

#: Minimums the spec text gives for integers (the schemas only say ``integer``).
_INT_MIN_V16 = {
    "BootNotificationConfirmation.interval": 0,
    "ChangeAvailabilityRequest.connectorId": 0,  # 0 = the whole Charge Point
    "MeterValuesRequest.connectorId": 0,
    "RemoteStartTransactionRequest.connectorId": 1,
    "StartTransactionRequest.connectorId": 1,
    "StatusNotificationRequest.connectorId": 0,
    "UnlockConnectorRequest.connectorId": 1,
    "GetDiagnosticsRequest.retries": 0,
    "GetDiagnosticsRequest.retryInterval": 0,
    "UpdateFirmwareRequest.retries": 0,
    "UpdateFirmwareRequest.retryInterval": 0,
    "GetLocalListVersionConfirmation.listVersion": -1,  # -1 = no list, 0 = empty list
    "ReserveNowRequest.connectorId": 0,
    "ClearChargingProfileRequest.connectorId": 0,
    "ClearChargingProfileRequest.stackLevel": 0,
    "GetCompositeScheduleRequest.connectorId": 0,
    "GetCompositeScheduleRequest.duration": 0,
    "GetCompositeScheduleConfirmation.connectorId": 0,
    "SetChargingProfileRequest.connectorId": 0,
    "ChargingProfile.stackLevel": 0,
    "ChargingSchedule.duration": 0,
    "ChargingSchedulePeriod.startPeriod": 0,
    "ChargingSchedulePeriod.numberPhases": 1,
    "TriggerMessageRequest.connectorId": 1,
}

_ARRAY_MIN_V16 = {
    "MeterValuesRequest.meterValue": 1,
    "MeterValue.sampledValue": 1,
    "ChargingSchedule.chargingSchedulePeriod": 1,
}

_RULES_V16 = {
    "ChargingSchedule": """
        if self.charging_schedule_period[0].start_period != 0:
            raise rule_error(
                "chargingSchedulePeriod.0.startPeriod", "the first period must start at 0"
            )
    """,
    "RemoteStartTransactionRequest": """
        profile = self.charging_profile
        purpose = profile.charging_profile_purpose if profile is not None else None
        if purpose is not None and purpose != ChargingProfilePurposeType.TX_PROFILE:
            raise rule_error("chargingProfile.chargingProfilePurpose", "must be TxProfile")
    """,
    "SendLocalListRequest": """
        seen: set[str] = set()
        for index, entry in enumerate(self.local_authorization_list or []):
            key = entry.id_tag.casefold()
            if key in seen:
                raise rule_error(
                    f"localAuthorizationList.{index}.idTag", "duplicate idTag in the list"
                )
            seen.add(key)
            if self.update_type == UpdateType.FULL and entry.id_tag_info is None:
                raise needed_error(f"localAuthorizationList.{index}.idTagInfo")
    """,
}

V16 = Profile(
    version="1.6",
    package="v16",
    schema_dir="docs/spec/1.6/schemas/json",
    request_suffix="Request",
    response_suffix="Confirmation",
    modules=_MODULES_V16,
    descriptions=_DESCRIPTIONS_V16,
    enums=_ENUMS_V16,
    types=_TYPES_V16,
    int_min=_INT_MIN_V16,
    array_min=_ARRAY_MIN_V16,
    empty_allowed=frozenset({"ChangeConfigurationRequest.value"}),
    rules=_RULES_V16,
    member_names={"kWh": "KWH", "kW": "KW", "kVA": "KVA", "SoC": "SOC"},
    sample_ints={"startPeriod": 0},
    # The security extension (roadmap phase 7).
    deferred=frozenset(
        {
            "CertificateSigned",
            "DeleteCertificate",
            "ExtendedTriggerMessage",
            "GetInstalledCertificateIds",
            "GetLog",
            "InstallCertificate",
            "LogStatusNotification",
            "SecurityEventNotification",
            "SignCertificate",
            "SignedFirmwareStatusNotification",
            "SignedUpdateFirmware",
        }
    ),
)
