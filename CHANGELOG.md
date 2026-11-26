# Changelog

All notable changes. The project follows semantic versioning from 1.0.0.

## [Unreleased]

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
