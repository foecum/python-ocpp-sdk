"""Tables that drive the generator: modules, names, constraints and spec-text rules.

Everything the JSON schemas do not say lives here. Names follow the spelling of
the specification so users can search the spec; the choices match go-ocpp-sdk.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Module:
    """One generated message module (an OCPP 1.6 feature profile)."""

    name: str
    title: str
    messages: tuple[str, ...]
    #: Handler name in the high-level APIs: ``<handler>Handler`` (and ``Unimplemented...``).
    handler: str = ""
    #: Name of the module's field in the ``Config`` classes.
    config_field: str = ""


@dataclass(frozen=True)
class Named:
    """A shared type or enum: its docstring and the schema locations it covers.

    A location is ``<schema file stem>.<json path>`` where array items are written
    ``[]`` (``MeterValues.meterValue[].sampledValue[]``).
    """

    doc: str
    locations: tuple[str, ...]


@dataclass(frozen=True)
class ExtraSet:
    """A CSV file of values that becomes a constants class and a tuple."""

    file: str
    cls: str
    tuple_name: str
    title: str


@dataclass(frozen=True)
class Profile:
    """Everything the generator needs to know about one OCPP version."""

    version: str
    package: str
    schema_dir: str
    request_suffix: str
    response_suffix: str
    modules: tuple[Module, ...]
    #: Messages whose request the Charge Point / Charging Station sends (the rest are sent by the
    #: CSMS); ``DataTransfer`` is sent by both.
    from_station: frozenset[str]
    descriptions: dict[str, str]
    enums: dict[str, Named] = field(default_factory=dict)
    types: dict[str, Named] = field(default_factory=dict)
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
    #: Name classes from the schemas' ``definitions`` (2.x) instead of the ``enums`` and ``types``
    #: tables: ``IdTokenType`` -> ``IdToken``, ``StatusEnumType`` -> ``Status``.
    definitions_naming: bool = False
    #: Name of the CALLERROR code class (in ``ocpp_sdk.errors``) the handlers use.
    error_codes: str = "ErrorCodeV16"
    #: The CSMS' session class, the handlers' name for its parameter and the station's typed calls.
    #: Directory of the appendices CSV files (relative to the repository root); ``""`` for none.
    appendices_dir: str = ""
    #: Suffix of the request schema file name (1.6: none, 2.x: ``Request``).
    request_file_suffix: str = ""
    station_module: str = "charge_point"
    session_class: str = "ChargePoint"
    session_param: str = "charge_point"
    station_calls: str = "ChargePointCalls"
    #: ``Model.wireName`` -> maximum for an integer or number field (``le``).
    int_max: dict[str, int] = field(default_factory=dict)
    #: number fields that accept at most one fractional digit (``Model.wireName``).
    one_decimal: frozenset[str] = frozenset()
    #: Optional fields (``Model.wireName``) that doctest samples include because a rule needs them.
    sample_fields: frozenset[str] = frozenset()
    #: One-way messages (OCPP 2.1 SEND): their schema is ``<Action>.json``, no response.
    one_way: frozenset[str] = frozenset()
    #: Value lists in the appendices CSV files that become constants (2.1).
    extra_sets: tuple[ExtraSet, ...] = ()
    #: messages with a schema that a later roadmap item generates.
    deferred: frozenset[str] = frozenset()
    #: ``Model.wireName`` -> type from ``ocpp_sdk.model`` replacing ``StrictStr`` (PEM, hex, ...).
    field_types: dict[str, str] = field(default_factory=dict)
    #: security event type -> whether the whitepaper calls it critical (module ``security``).
    security_events: dict[str, bool] = field(default_factory=dict)


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
        "Core",
        "core",
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
        "Firmware",
        "firmware",
    ),
    Module(
        "localauth",
        "Local Auth List Management",
        ("GetLocalListVersion", "SendLocalList"),
        "LocalAuthList",
        "local_auth_list",
    ),
    Module(
        "reservation",
        "Reservation",
        ("CancelReservation", "ReserveNow"),
        "Reservation",
        "reservation",
    ),
    Module(
        "smartcharging",
        "Smart Charging",
        ("ClearChargingProfile", "GetCompositeSchedule", "SetChargingProfile"),
        "SmartCharging",
        "smart_charging",
    ),
    Module(
        "remotetrigger", "Remote Trigger", ("TriggerMessage",), "RemoteTrigger", "remote_trigger"
    ),
    Module(
        "security",
        "Security",
        (
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
        ),
        "Security",
        "security",
    ),
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
    "CertificateSigned": "Delivers the certificate chain the CA signed for a SignCertificate.",
    "DeleteCertificate": "Asks the Charge Point to delete an installed certificate.",
    "ExtendedTriggerMessage": "Asks the Charge Point to send a message, including the new ones.",
    "GetInstalledCertificateIds": "Asks which certificates of a kind are installed.",
    "GetLog": "Asks the Charge Point to upload a diagnostics or security log.",
    "InstallCertificate": "Asks the Charge Point to install a root certificate.",
    "LogStatusNotification": "Reports the progress of a log upload.",
    "SecurityEventNotification": "Reports a security event to the Central System.",
    "SignCertificate": "Asks the Central System to have a certificate signed (CSR).",
    "SignedFirmwareStatusNotification": "Reports the progress of a signed firmware update.",
    "SignedUpdateFirmware": "Asks the Charge Point to install firmware with a signature.",
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
        "The answer to TriggerMessage and ExtendedTriggerMessage.",
        _loc(
            "TriggerMessageResponse.status",
            "ExtendedTriggerMessageResponse#TriggerMessageStatusEnumType",
        ),
    ),
    "CertificateUse": Named(
        "The kind of root certificate.",
        _loc(
            "InstallCertificate#CertificateUseEnumType",
            "GetInstalledCertificateIds#CertificateUseEnumType",
        ),
    ),
    "HashAlgorithm": Named(
        "The hash algorithm of a CertificateHashData.",
        _loc(
            "DeleteCertificate#HashAlgorithmEnumType",
            "GetInstalledCertificateIdsResponse#HashAlgorithmEnumType",
        ),
    ),
    "GetInstalledCertificateStatus": Named(
        "The answer to GetInstalledCertificateIds.",
        _loc("GetInstalledCertificateIdsResponse#GetInstalledCertificateStatusEnumType"),
    ),
    "ExtendedMessageTrigger": Named(
        "The message an ExtendedTriggerMessage asks for.",
        _loc("ExtendedTriggerMessage#MessageTriggerEnumType"),
    ),
    "LogType": Named("The kind of log to upload.", _loc("GetLog#LogEnumType")),
    "UploadLogStatus": Named(
        "The progress of a log upload.", _loc("LogStatusNotification#UploadLogStatusEnumType")
    ),
    "SignedFirmwareStatus": Named(
        "The progress of a signed firmware update.",
        _loc("SignedFirmwareStatusNotification#FirmwareStatusEnumType"),
    ),
    "CertificateSignedStatus": Named(
        "The answer to CertificateSigned.",
        _loc("CertificateSignedResponse#CertificateSignedStatusEnumType"),
    ),
    "InstallCertificateStatus": Named(
        "The answer to InstallCertificate.",
        _loc("InstallCertificateResponse#InstallCertificateStatusEnumType"),
    ),
    "DeleteCertificateStatus": Named(
        "The answer to DeleteCertificate.",
        _loc("DeleteCertificateResponse#DeleteCertificateStatusEnumType"),
    ),
    "LogStatus": Named("The answer to GetLog.", _loc("GetLogResponse#LogStatusEnumType")),
    "SignedUpdateFirmwareStatus": Named(
        "The answer to SignedUpdateFirmware.",
        _loc("SignedUpdateFirmwareResponse#UpdateFirmwareStatusEnumType"),
    ),
    "GenericStatus": Named(
        "The answer to SignCertificate.", _loc("SignCertificateResponse#GenericStatusEnumType")
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
    "CertificateHashData": Named(
        "Identifies an installed certificate by hashes of its issuer and its serial number.",
        _loc(
            "DeleteCertificate#CertificateHashDataType",
            "GetInstalledCertificateIdsResponse#CertificateHashDataType",
        ),
    ),
    "LogParameters": Named("Which log to upload and where.", _loc("GetLog#LogParametersType")),
    "Firmware": Named(
        "The signed firmware of a SignedUpdateFirmware.", _loc("SignedUpdateFirmware#FirmwareType")
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
    "ExtendedTriggerMessageRequest.connectorId": 1,
    "GetLogRequest.retries": 0,
    "GetLogRequest.retryInterval": 0,
    "SignedUpdateFirmwareRequest.retries": 0,
    "SignedUpdateFirmwareRequest.retryInterval": 0,
}

_ARRAY_MIN_V16 = {
    "MeterValuesRequest.meterValue": 1,
    "MeterValue.sampledValue": 1,
    "ChargingSchedule.chargingSchedulePeriod": 1,
    # The spec says 0..* where the schema says minItems 1 (an override, not a minimum).
    "GetInstalledCertificateIdsConfirmation.certificateHashData": 0,
}

_FIELD_TYPES_V16 = {
    "SignCertificateRequest.csr": "PemCsr",
    "CertificateSignedRequest.certificateChain": "PemCertificates",
    "InstallCertificateRequest.certificate": "PemCertificate",
    "Firmware.signingCertificate": "PemCertificate",
    "Firmware.signature": "Base64",
    "Firmware.location": "AbsoluteURI",
    "LogParameters.remoteLocation": "AbsoluteURI",
    "CertificateHashData.issuerNameHash": "HexBytes",
    "CertificateHashData.issuerKeyHash": "HexBytes",
    "CertificateHashData.serialNumber": "Hex",
}

#: The security events of the whitepaper (edition 3, table "Security events") and whether
#: each is critical. ``SecurityEventNotification.type`` stays an open string.
_SECURITY_EVENTS_V16 = {
    "FirmwareUpdated": True,
    "FailedToAuthenticateAtCentralSystem": False,
    "CentralSystemFailedToAuthenticate": False,
    "SettingSystemTime": True,
    "StartupOfTheDevice": True,
    "ResetOrReboot": True,
    "SecurityLogWasCleared": True,
    "ReconfigurationOfSecurityParameters": False,
    "MemoryExhaustion": True,
    "InvalidMessages": False,
    "AttemptedReplayAttacks": False,
    "TamperDetectionActivated": True,
    "InvalidFirmwareSignature": False,
    "InvalidFirmwareSigningCertificate": False,
    "InvalidCentralSystemCertificate": False,
    "InvalidChargePointCertificate": False,
    "InvalidTLSVersion": False,
    "InvalidTLSCipherSuite": False,
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
    from_station=frozenset(
        {
            "Authorize",
            "BootNotification",
            "DiagnosticsStatusNotification",
            "FirmwareStatusNotification",
            "Heartbeat",
            "MeterValues",
            "StartTransaction",
            "StatusNotification",
            "StopTransaction",
            "LogStatusNotification",
            "SecurityEventNotification",
            "SignCertificate",
            "SignedFirmwareStatusNotification",
        }
    ),
    descriptions=_DESCRIPTIONS_V16,
    enums=_ENUMS_V16,
    types=_TYPES_V16,
    int_min=_INT_MIN_V16,
    array_min=_ARRAY_MIN_V16,
    empty_allowed=frozenset({"ChangeConfigurationRequest.value"}),
    rules=_RULES_V16,
    member_names={"kWh": "KWH", "kW": "KW", "kVA": "KVA", "SoC": "SOC"},
    sample_ints={"startPeriod": 0},
    field_types=_FIELD_TYPES_V16,
    security_events=_SECURITY_EVENTS_V16,
)


# ---------------------------------------------------------------------------------------------
# OCPP 2.0.1
# ---------------------------------------------------------------------------------------------

_MODULES_V201 = (
    Module(
        "security",
        "A Security",
        ("CertificateSigned", "SecurityEventNotification", "SignCertificate"),
        "Security",
        "security",
    ),
    Module(
        "provisioning",
        "B Provisioning",
        (
            "BootNotification",
            "GetBaseReport",
            "GetReport",
            "GetVariables",
            "NotifyReport",
            "Reset",
            "SetNetworkProfile",
            "SetVariables",
        ),
        "Provisioning",
        "provisioning",
    ),
    Module(
        "authorization",
        "C Authorization",
        ("Authorize", "ClearCache"),
        "Authorization",
        "authorization",
    ),
    Module(
        "localauthlist",
        "D Local Authorization List",
        ("GetLocalListVersion", "SendLocalList"),
        "LocalAuthList",
        "local_auth_list",
    ),
    Module(
        "transactions",
        "E Transactions",
        ("GetTransactionStatus", "TransactionEvent"),
        "Transactions",
        "transactions",
    ),
    Module(
        "remotecontrol",
        "F Remote Control",
        ("RequestStartTransaction", "RequestStopTransaction", "TriggerMessage", "UnlockConnector"),
        "RemoteControl",
        "remote_control",
    ),
    Module(
        "availability",
        "G Availability",
        ("ChangeAvailability", "Heartbeat", "StatusNotification"),
        "Availability",
        "availability",
    ),
    Module(
        "reservation",
        "H Reservation",
        ("CancelReservation", "ReservationStatusUpdate", "ReserveNow"),
        "Reservation",
        "reservation",
    ),
    Module(
        "tariffandcost", "I Tariff and Cost", ("CostUpdated",), "TariffAndCost", "tariff_and_cost"
    ),
    Module("metervalues", "J Meter Values", ("MeterValues",), "MeterValues", "meter_values"),
    Module(
        "smartcharging",
        "K Smart Charging",
        (
            "ClearChargingProfile",
            "ClearedChargingLimit",
            "GetChargingProfiles",
            "GetCompositeSchedule",
            "NotifyChargingLimit",
            "NotifyEVChargingNeeds",
            "NotifyEVChargingSchedule",
            "ReportChargingProfiles",
            "SetChargingProfile",
        ),
        "SmartCharging",
        "smart_charging",
    ),
    Module(
        "firmware",
        "L Firmware Management",
        (
            "FirmwareStatusNotification",
            "PublishFirmware",
            "PublishFirmwareStatusNotification",
            "UnpublishFirmware",
            "UpdateFirmware",
        ),
        "Firmware",
        "firmware",
    ),
    Module(
        "iso15118",
        "M ISO 15118 Certificate Management",
        (
            "DeleteCertificate",
            "Get15118EVCertificate",
            "GetCertificateStatus",
            "GetInstalledCertificateIds",
            "InstallCertificate",
        ),
        "ISO15118",
        "iso15118",
    ),
    Module(
        "diagnostics",
        "N Diagnostics",
        (
            "ClearVariableMonitoring",
            "CustomerInformation",
            "GetLog",
            "GetMonitoringReport",
            "LogStatusNotification",
            "NotifyCustomerInformation",
            "NotifyEvent",
            "NotifyMonitoringReport",
            "SetMonitoringBase",
            "SetMonitoringLevel",
            "SetVariableMonitoring",
        ),
        "Diagnostics",
        "diagnostics",
    ),
    Module(
        "displaymessage",
        "O Display Message",
        ("ClearDisplayMessage", "GetDisplayMessages", "NotifyDisplayMessages", "SetDisplayMessage"),
        "DisplayMessage",
        "display_message",
    ),
    Module("datatransfer", "P Data Transfer", ("DataTransfer",), "DataTransfer", "data_transfer"),
)

#: The messages whose request the Charging Station sends (OCPP 2.0.1 part 2 scenarios).
_FROM_STATION_V201 = frozenset(
    {
        "Authorize",
        "BootNotification",
        "ClearedChargingLimit",
        "FirmwareStatusNotification",
        "Get15118EVCertificate",
        "GetCertificateStatus",
        "Heartbeat",
        "LogStatusNotification",
        "MeterValues",
        "NotifyChargingLimit",
        "NotifyCustomerInformation",
        "NotifyDisplayMessages",
        "NotifyEVChargingNeeds",
        "NotifyEVChargingSchedule",
        "NotifyEvent",
        "NotifyMonitoringReport",
        "NotifyReport",
        "PublishFirmwareStatusNotification",
        "ReportChargingProfiles",
        "ReservationStatusUpdate",
        "SecurityEventNotification",
        "SignCertificate",
        "StatusNotification",
        "TransactionEvent",
    }
)

_RULES_V201 = {
    "SendLocalListRequest": """
        if self.update_type == Update.FULL:
            for index, entry in enumerate(self.local_authorization_list or []):
                if entry.id_token_info is None:
                    raise needed_error(f"localAuthorizationList.{index}.idTokenInfo")
    """,
    "RequestStartTransactionRequest": """
        profile = self.charging_profile
        purpose = profile.charging_profile_purpose if profile is not None else None
        if purpose is not None and purpose != ChargingProfilePurpose.TX_PROFILE:
            raise rule_error("chargingProfile.chargingProfilePurpose", "must be TxProfile")
    """,
    "ChargingProfile": """
        if (
            self.transaction_id
            and self.charging_profile_purpose != ChargingProfilePurpose.TX_PROFILE
        ):
            raise rule_error(
                "transactionId", "only allowed when chargingProfilePurpose is TxProfile"
            )
    """,
    "VariableCharacteristics": """
        lists = (
            Data.OPTION_LIST,
            Data.MEMBER_LIST,
            Data.SEQUENCE_LIST,
        )
        if not self.values_list and self.data_type in lists:
            raise needed_error("valuesList")
    """,
    "PublishFirmwareStatusNotificationRequest": """
        if self.status == PublishFirmwareStatus.PUBLISHED and not self.location:
            raise needed_error("location")
    """,
}

V201 = Profile(
    version="2.0.1",
    package="v201",
    schema_dir="docs/spec/2.0.1/schemas",
    request_suffix="Request",
    response_suffix="Response",
    modules=_MODULES_V201,
    from_station=_FROM_STATION_V201,
    descriptions={},
    definitions_naming=True,
    appendices_dir="docs/spec/2.0.1/Appendices_CSV_v1.5",
    request_file_suffix="Request",
    error_codes="ErrorCodeV2",
    station_module="charging_station",
    session_class="ChargingStation",
    session_param="charging_station",
    station_calls="ChargingStationCalls",
    int_min={
        "NotifyChargingLimitRequest.evseId": 1,
        "NotifyEVChargingScheduleRequest.evseId": 1,
        "RequestStartTransactionRequest.evseId": 1,
        "ChargingSchedulePeriod.phaseToUse": 1,
        "SetMonitoringLevelRequest.severity": 0,
    },
    int_max={"ChargingSchedulePeriod.phaseToUse": 3, "SetMonitoringLevelRequest.severity": 9},
    one_decimal=frozenset({"ChargingSchedulePeriod.limit"}),
    empty_allowed=frozenset({"SetVariableData.attributeValue"}),
    rules=_RULES_V201,
)


# ---------------------------------------------------------------------------------------------
# OCPP 2.1
# ---------------------------------------------------------------------------------------------

#: The messages OCPP 2.1 adds to the blocks it shares with 2.0.1, in the order of the block's
#: functional requirements.
_EXTRA_V21 = {
    "authorization": ("NotifySettlement", "NotifyWebPaymentStarted", "VatNumberValidation"),
    "tariffandcost": ("ChangeTransactionTariff", "ClearTariffs", "GetTariffs", "SetDefaultTariff"),
    "smartcharging": (
        "NotifyPriorityCharging",
        "PullDynamicScheduleUpdate",
        "UpdateDynamicSchedule",
        "UsePriorityCharging",
    ),
    "iso15118": ("GetCertificateChainStatus",),
    "diagnostics": (
        "AdjustPeriodicEventStream",
        "ClosePeriodicEventStream",
        "GetPeriodicEventStream",
        "NotifyPeriodicEventStream",
        "OpenPeriodicEventStream",
    ),
}

_MODULES_V21 = (
    *(
        replace(
            m,
            messages=(*m.messages, *_EXTRA_V21.get(m.name, ())),
            title="M Certificate Management" if m.name == "iso15118" else m.title,
        )
        for m in _MODULES_V201
    ),
    Module(
        "bidirectional",
        "Q Bidirectional Power Transfer",
        ("AFRRSignal", "NotifyAllowedEnergyTransfer"),
        "Bidirectional",
        "bidirectional",
    ),
    Module(
        "dercontrol",
        "R DER Control",
        (
            "ClearDERControl",
            "GetDERControl",
            "NotifyDERAlarm",
            "NotifyDERStartStop",
            "ReportDERControl",
            "SetDERControl",
        ),
        "DERControl",
        "der_control",
    ),
    Module(
        "batteryswap",
        "S Battery Swapping",
        ("BatterySwap", "RequestBatterySwap"),
        "BatterySwap",
        "battery_swap",
    ),
)

#: The senders of the 27 messages 2.1 adds are stated in the scenarios of OCPP 2.1 part 2.
_FROM_STATION_V21 = _FROM_STATION_V201 | {
    "BatterySwap",
    "ClosePeriodicEventStream",
    "GetCertificateChainStatus",
    "NotifyDERAlarm",
    "NotifyDERStartStop",
    "NotifyPeriodicEventStream",
    "NotifyPriorityCharging",
    "NotifySettlement",
    "OpenPeriodicEventStream",
    "PullDynamicScheduleUpdate",
    "ReportDERControl",
    "VatNumberValidation",
}

_NOT_STANDALONE = """
        if self.control_type == DERControl.POWER_MONITORING_MUST_TRIP:
            raise rule_error(
                "controlType", "PowerMonitoringMustTrip is not a stand-alone DER control"
            )
"""

_RULES_V21 = {
    **_RULES_V201,
    # In 2.1 a period may carry a setpoint instead of a limit; the V2X curves need two points.
    "ChargingSchedulePeriod": """
        curve = self.v2x_freq_watt_curve
        mode = self.operation_mode
        if curve is None and mode == OperationMode.LOCAL_FREQUENCY:
            raise needed_error("v2xFreqWattCurve")
        if curve is not None and len(curve) < 2:
            raise rule_error("v2xFreqWattCurve", "must contain at least two coordinates")
        signal = self.v2x_signal_watt_curve
        if signal is not None and len(signal) < 2:
            raise rule_error("v2xSignalWattCurve", "must contain at least two coordinates")
    """,
    "ChargingProfile": _RULES_V201["ChargingProfile"]
    + """
        tx_purposes = (ChargingProfilePurpose.TX_PROFILE, ChargingProfilePurpose.TX_DEFAULT_PROFILE)
        for index, schedule in enumerate(self.charging_schedule):
            if schedule.randomized_delay and self.charging_profile_purpose not in tx_purposes:
                raise rule_error(
                    f"chargingSchedule.{index}.randomizedDelay",
                    "only allowed for TxProfile and TxDefaultProfile",
                )
    """,
    # Errata 2026-09, 2.28: pctMaxDischargePower is required, as a percentage.
    "LimitMaxDischarge": """
        if self.pct_max_discharge_power is None:
            raise needed_error("pctMaxDischargePower")
    """,
    # Errata 2026-09, 2.30: PowerMonitoringMustTrip is not a valid stand-alone DER control.
    "SetDERControlRequest": _NOT_STANDALONE,
    "GetDERControlRequest": _NOT_STANDALONE,
    "ClearDERControlRequest": _NOT_STANDALONE,
    "NotifyDERAlarmRequest": _NOT_STANDALONE,
    # "This value is mandatory if hv10MinMeanTripDelay is set" and the reverse.
    "VoltageParams": """
        if self.hv10_min_mean_trip_delay is not None and self.hv10_min_mean_value is None:
            raise needed_error("hv10MinMeanValue")
        if self.hv10_min_mean_value is not None and self.hv10_min_mean_trip_delay is None:
            raise needed_error("hv10MinMeanTripDelay")
    """,
    # "Must be in 24h format with leading zeros" and "RFC 3339 full-date" (YYYY-MM-DD).
    "TariffConditions": "TARIFF_CONDITIONS",
    "TariffConditionsFixed": "TARIFF_CONDITIONS",
}
_TARIFF_CONDITIONS = """
        for wire, value in (
            ("startTimeOfDay", self.start_time_of_day),
            ("endTimeOfDay", self.end_time_of_day),
        ):
            if value is not None and not time_of_day_ok(value):
                raise rule_error(wire, "must be HH:MM in 24h format with leading zeros")
        for wire, value in (
            ("validFromDate", self.valid_from_date),
            ("validToDate", self.valid_to_date),
        ):
            if value is not None and not full_date_ok(value):
                raise rule_error(wire, "must be a date written YYYY-MM-DD")
"""
_RULES_V21 = {
    k: (_TARIFF_CONDITIONS if v == "TARIFF_CONDITIONS" else v) for k, v in _RULES_V21.items()
}

V21 = Profile(
    version="2.1",
    package="v21",
    schema_dir="docs/spec/2.1/schemas",
    request_suffix="Request",
    response_suffix="Response",
    modules=_MODULES_V21,
    from_station=_FROM_STATION_V21,
    descriptions={},
    definitions_naming=True,
    appendices_dir="docs/spec/2.1/Appendices_CSV_v2.1",
    request_file_suffix="Request",
    error_codes="ErrorCodeV2",
    station_module="charging_station",
    session_class="ChargingStation",
    session_param="charging_station",
    station_calls="ChargingStationCalls",
    one_way=frozenset({"NotifyPeriodicEventStream"}),
    sample_fields=frozenset({"LimitMaxDischarge.pctMaxDischargePower"}),
    int_min={
        **V201.int_min,
        "LimitMaxDischarge.pctMaxDischargePower": 0,
    },
    int_max={**V201.int_max, "LimitMaxDischarge.pctMaxDischargePower": 100},
    one_decimal=frozenset({"ChargingSchedulePeriod.limit"}),
    empty_allowed=frozenset({"SetVariableData.attributeValue"}),
    rules=_RULES_V21,
    extra_sets=(
        ExtraSet("idtokenenumtype.csv", "IdTokenType", "ID_TOKEN_TYPES", "idToken types"),
        ExtraSet("connectorenumtype.csv", "ConnectorType", "CONNECTOR_TYPES", "connector types"),
        ExtraSet(
            "charginglimitsourceenumtype.csv",
            "ChargingLimitSource",
            "CHARGING_LIMIT_SOURCES",
            "charging limit sources",
        ),
        ExtraSet("paymentbrand.csv", "PaymentBrand", "PAYMENT_BRANDS", "payment brands"),
        ExtraSet(
            "paymentrecognition.csv",
            "PaymentRecognition",
            "PAYMENT_RECOGNITIONS",
            "payment recognitions",
        ),
        ExtraSet(
            "additional_info_types.csv",
            "AdditionalInfoType",
            "ADDITIONAL_INFO_TYPES",
            "additionalInfo types",
        ),
        ExtraSet(
            "additional_info_types_adhoc.csv",
            "AdditionalInfoAdHocType",
            "ADDITIONAL_INFO_ADHOC_TYPES",
            "additionalInfo types for ad hoc payments",
        ),
        ExtraSet("signingmethod.csv", "SigningMethod", "SIGNING_METHODS", "signing methods"),
    ),
)
