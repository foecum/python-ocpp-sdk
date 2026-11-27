# Changelog

All notable changes. The project follows semantic versioning from 1.0.0.

## [1.1.1] - Fixes

### Fixed

- `ocpp_sdk.datetime.format` zero-pads years below 1000 (Python 3.11 sent `999-...`).
- The 1.6 `TransactionQueue` keeps delivering when `on_discard` raises, a stored message no longer
  validates, a stored item is malformed or a save fails; saves made while delivering run in a worker
  thread.
- The client keeps reconnecting when its `on_connect` callback or the sink's `close` raises.
- CSMS: `on_disconnect` now runs for a session replaced by a reconnect with the same ID; a failing
  `on_connect` hook closes the session's endpoint (and is not followed by `on_disconnect`).

### Added

- `Registry.__contains__` (`"Heartbeat" in registry`).

## [1.1.0] - OCPP 2.1

### Added
- OCPP 2.1: 91 messages in 19 block modules (`ocpp_sdk.v21`, its own types, no dependency on
  `v201`), generated from the official schemas, with the rules of the spec text and errata 2026-09;
  handler protocols, typed calls, `ChargingStation` and `CSMS`; appendices constants (components,
  variables, units, reason codes, security events, idToken and connector types, payment brands,
  signing methods, ...).
- `ocppj`: the 2.1 frame types SEND (`[6, ...]`) and CALLRESULTERROR (`[5, ...]`).
  `Endpoint.send` writes an unconfirmed message; incoming SENDs reach `send_handler` one at a time
  in arrival order; an undecodable CALLRESULT is answered with a CALLRESULTERROR.
  `NotifyPeriodicEventStream` is the one standard SEND message
  (`ChargingStation.notify_periodic_event_stream`, `CSMS` `Config.send_handler`).
- 2.1 examples, schema round-trip and mutation tests, property tests, benchmarks, load test and
  interop tests against go-ocpp-sdk.

## [1.0.0] - OCPP 1.6J and 2.0.1, API approved

The public API of `ocpp_sdk` (see `docs/api-review.md`) is stable: breaking changes need a new
major version. OCPP 2.1 is planned as an addition (1.1.0).

### Added
- Property tests (Hypothesis) for frame parsing, message decoding, date-times and the endpoint;
  `fuzz.yml` runs them weekly with a large example count.
- Benchmarks (`tests/benchmarks`), a load test (`examples/loadtest`), `docs/benchmarks.md` and
  `docs/api-review.md`.
- `ocpp_sdk` re-exports the exceptions and `Version`.

### Fixed
- A date-time with less than one millisecond of fraction was sent as `...:00.000Z`; it is now sent
  as whole seconds.

## [0.2.0] - OCPP 2.0.1

### Added
- OCPP 2.0.1: 64 messages in 16 functional-block modules, generated from the official schemas;
  handler protocols, typed calls, `ChargingStation` and `CSMS`; the standardized components,
  variables, units, reason codes and security events as constants.
- Examples and go-ocpp-sdk interop tests for 2.0.1.

### Changed
- The 1.6 `ChargePoint` and `CSMS` share their lifecycle code with the 2.0.1 classes.

## [0.1.0] - OCPP 1.6J

### Added
- Errors, date-times, OCPP-J framing and the transport-agnostic endpoint.
- WebSocket server and client with OCPP-J 5.4 reconnect, security profiles 1 to 3, graceful
  shutdown.
- OCPP 1.6: 28 messages of the six feature profiles and the 11 messages of the security extension,
  generated from the official schemas; `ChargePoint` and `CSMS`; the transaction message queue;
  AuthorizationKey helpers; examples; go-ocpp-sdk interop tests.
