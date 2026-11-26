# Public API review (before v1.0.0)

Reviewed 2026-11-27 against `AGENTS.md` section 4: naming, consistency between OCPP 1.6 and
2.0.1, docstrings, typing and what is exposed. The owner approves this review before the
v1.0.0 tag; from then on breaking changes need a new major version.

## Checked and fine

- **Docstrings.** A script walked every public module (everything not under `_internal`) and
  found 559 public classes and functions, none without a docstring (methods and properties of
  those classes included). Generated modules take theirs from the schemas.
- **Typing.** `py.typed` ships; `mypy --strict` passes over `src`, `tests`, `tools`, `scripts`
  and `examples`.
- **Same shape across versions.** `ChargePoint` (1.6) and `ChargingStation` (2.0.1) have the same
  lifecycle (`start`, `wait_connected`, `wait_online`, `close`, async context manager), typed
  calls with `timeout=`, `connected` and `connection`. `CSMS` has the same members in both:
  `charge_point_ids()`, `charge_point(id)`, `for_each`, `on_connect` / `on_disconnect`,
  `shutdown(timeout)`, calls by station ID. Handlers are `on_<message>`, sync or async, with the
  session first on the CSMS side; both versions share `_internal/lifecycle.py`.
- **Nothing internal leaks.** Public classes hold `_core` objects and forward to them; no public
  signature mentions `ocpp_sdk._internal`.
- **Errors.** One hierarchy under `OCPPError` (`NotConnectedError`, `CallTimeoutError`,
  `CallError`, `ValidationError`, `QueueFullError`); handlers never leak exception text to the
  peer.
- **Wire behaviour** is covered by schema mutation tests (1.6: every field of every message;
  2.0.1: 9,580 mutations), property tests, and interop tests against go-ocpp-sdk v1.1.0 in both
  directions for both versions.

## Changed in this review

- `ocpp_sdk` now re-exports the everyday names: the exceptions and `Version`
  (`from ocpp_sdk import CallError, NotConnectedError, Version`).
- `ocpp_sdk.datetime.format` no longer sends `.000Z` for a value with less than a millisecond
  of fraction; it sends whole seconds (found by the fuzzer).

## Things to know before 1.0 (not changed)

- **Enum names that follow the stripping rule literally.** 2.0.1 has enums called `Data`
  (`DataEnumType`) and `Update` (`UpdateEnumType`) in `ocpp_sdk.v201.types`. They are correct
  by the naming rule and search well against the spec, but read oddly. Renaming later is a
  breaking change, so say now if you want others (e.g. `VariableDataType`, `UpdateType`).
- **`ChargePoint` names two classes.** `v16.charge_point.ChargePoint` is the client and
  `v16.csms.ChargePoint` is the CSMS's session object. The same applies to `ChargingStation` in
  2.0.1. They live in different modules and this follows `AGENTS.md`; type hints in handlers
  usually import the session as `from ocpp_sdk.v16.csms import ChargePoint as Session`.
- **The CSMS session uses `charge_point_id`** in 2.0.1 too (the spec calls the peer a Charging
  Station, the URL identity is the same thing). Kept for symmetry with 1.6.
- **`Connection.send(text)` is public.** It writes a raw frame; it is for the transport and for
  tests, and an application that uses it bypasses correlation. Not exposed through the high-level
  classes.
- **One outstanding call per direction.** By design (OCPP-J); a second call waits in a queue of
  1,000 (`QueueFullError` beyond that).
- **Not implemented yet:** OCPP 2.1 (phase 10). 2.1 does not touch the 1.6 and 2.0.1 APIs,
  which is why 1.0.0 can be tagged first.
