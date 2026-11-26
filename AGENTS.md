# AGENTS.md — python-ocpp-sdk

Instructions for AI coding agents (Claude Code, Codex, etc.) working in this repo.
Read this whole file at the start of every session. It is the source of truth for
scope, layout, conventions and progress.

## 1. Project

A Python SDK for **OCPP** (Open Charge Point Protocol), the protocol between EV
charging stations and their central management system.

Sister project of **go-ocpp-sdk** (`github.com/foecum/go-ocpp-sdk`, v1.1.0: OCPP 1.6J,
2.0.1 and 2.1 complete). The Go SDK has already settled most protocol questions;
section 4 lists those decisions and this SDK follows them. Keep behaviour identical
on the wire; write idiomatic Python, not translated Go.

- Repo: `github.com/foecum/python-ocpp-sdk`
- PyPI distribution name: `ocpp-sdk` (the name `ocpp` is taken by another project)
- Import package: `ocpp_sdk`
- Python: **3.11+** (test on 3.11 through the latest stable release)
- Licence: MIT, same as go-ocpp-sdk (confirm with the owner in Phase 0)
- Async-first (`asyncio`). No sync API unless the owner asks for one.
- Roles supported: **Charge Point / Charging Station** (client) and
  **Central System / CSMS** (server)
- Transport: **OCPP-J only** (JSON over WebSocket). No SOAP (OCPP-S).
- Protocol versions, in order: **OCPP 1.6J** → **OCPP 2.0.1** → **OCPP 2.1**

## 2. Source of truth for the spec

- Official specs and JSON schemas go in `docs/spec/` (download from
  <https://openchargealliance.org/my-oca/ocpp/>; the owner adds them). JSON (OCPP-J)
  only — this SDK does not implement SOAP (OCPP-S).
  - `docs/spec/1.6/` — OCPP 1.6 edition 2 PDF, OCPP-J 1.6 specification,
    both errata sheets, the OCPP 1.6 Security Whitepaper (edition 3) and its
    schemas, `schemas/` (JSON schemas)
  - `docs/spec/2.0.1/` — OCPP 2.0.1 edition 4: parts 0–2, part 2 appendices,
    part 4 (OCPP-J), errata, `appendices-csv/`, `schemas/`; parts 5–6
    (certification profiles, test cases) for checking behaviour only
  - `docs/spec/2.1/` — OCPP 2.1 edition 2, same structure
- `docs/spec/` is never published or packaged (the OCA documents are not ours to
  redistribute). Exclude it from the sdist and wheel and from the docs site.
- Order of precedence when documents disagree: errata sheet → OCPP-J spec
  (for framing/transport) → main specification → JSON schema. If a schema and
  the spec text still conflict after errata, record it in "Known gaps" and ask.
- Field names, required/optional, max string lengths, enum values and cardinality
  come from those files. **Never guess.** If the spec is missing or unclear, stop
  and ask the owner. When go-ocpp-sdk already answered the question (section 4),
  follow it and say so in the commit message.
- The appendices CSVs (2.0.1/2.1) are the machine-readable source for standardized
  components and variables (used by GetVariables/SetVariables); prefer them over
  copying tables out of the PDF.
- Watch the spelling differences between versions in CALLERROR codes:
  1.6 uses `FormationViolation` and `OccurenceConstraintViolation` (sic);
  2.0.1 and 2.1 use `FormatViolation` and `OccurrenceConstraintViolation`.
  OCPP 2.1 uses the 2.0.1 code set (2.1 OCPP-J table 8).

## 3. Layout

Standard Python `src/` layout (unlike Go, `src/` is the norm here: it stops tests
from importing the package from the working tree instead of the installed copy).

```
python-ocpp-sdk/
├── pyproject.toml
├── src/ocpp_sdk/
│   ├── __init__.py          // public re-exports, __version__
│   ├── py.typed             // ships type hints (PEP 561)
│   ├── errors.py            // exception hierarchy, CallError, ErrorCode sets per version
│   ├── datetime.py          // the one date-time parse/format for every version
│   ├── ocppj/               // OCPP-J framing, version-agnostic
│   │   ├── frames.py        // Call, CallResult, CallErrorFrame, Send, CallResultError
│   │   ├── registry.py      // action -> request/response models, decode + validate
│   │   └── endpoint.py      // correlation, timeouts, queue, dispatch (transport-agnostic)
│   ├── transport/           // WebSocket transport, version-agnostic
│   │   ├── server.py
│   │   ├── client.py        // incl. reconnect (OCPP-J §5.4)
│   │   └── auth.py          // Basic auth, TLS contexts, client-cert identity checks
│   ├── v16/
│   │   ├── types.py         // shared 1.6 datatypes + enums
│   │   ├── core.py, firmware.py, localauth.py, reservation.py,
│   │   │   smartcharging.py, remotetrigger.py   // messages per feature profile
│   │   ├── security.py      // 1.6 security whitepaper extension (Phase 7)
│   │   ├── charge_point.py  // high-level client API
│   │   ├── transaction_queue.py  // opt-in 1.6 transaction message queue
│   │   └── csms.py          // high-level server API
│   ├── v201/
│   │   ├── types.py         // generated shared datatypes + enums
│   │   ├── <block>.py       // generated, one module per functional block
│   │   ├── appendices.py    // generated constants from the appendices CSVs
│   │   ├── handlers.py      // generated handler protocols + Unimplemented bases
│   │   ├── charging_station.py
│   │   └── csms.py
│   ├── v21/                 // same layout as v201, plus bidirectional, dercontrol,
│   │                        // batteryswap; does not import v201
│   └── _internal/           // helpers not part of the public API (rules checks,
│                            // shared CSMS/station lifecycle)
├── tools/gen/               // code generator: schemas + CSVs -> v16/v201/v21 modules
│   └── profiles.py          // block table, directions, handler names, spec-text rules
├── scripts/coverage.py      // enforces the 95% per-package floor (section 4)
├── tests/
│   ├── unit/
│   ├── schema/              // schema mutation tests against the official schemas
│   ├── integration/
│   ├── interop/             // against go-ocpp-sdk (section 7)
│   └── fixtures/            // sample payloads
├── examples/
│   ├── v16/charge_point.py   v16/csms.py
│   ├── v201/charging_station.py   v201/csms.py
│   ├── v21/charging_station.py   v21/csms.py
│   └── loadtest/
├── site/                    // HTML documentation site (GitHub Pages), see section 10
├── docs/
│   ├── spec/                // OCA specs, never published
│   ├── benchmarks.md
│   └── api-review.md
└── .github/workflows/       // ci.yml, pages.yml, fuzz.yml, release.yml
```

## 4. Conventions

### Tooling

- `uv` for environments and builds, `hatchling` as build backend, `ruff` for lint
  and format, `mypy --strict` for types, `pytest` + `pytest-asyncio`,
  `pytest-cov` (branch coverage on), `hypothesis` for property/fuzz tests,
  `pytest-benchmark` for benchmarks, `jsonschema` for schema tests (dev only).
- Runtime dependencies: `pydantic` (v2) and one WebSocket library only. Any new
  runtime dependency must be justified in "Decisions" and approved by the owner.
  Dev-only deps go in a `dev` dependency group.

### Models and generation

- Pydantic v2 models. Python attributes are snake_case; JSON uses the spec's exact
  camelCase via `alias_generator=to_camel`, `populate_by_name=True`; serialise with
  `by_alias=True, exclude_none=True` so absent optional fields are not sent.
- **All** message models (1.6, its security extension, 2.0.1, 2.1), shared types,
  enums, appendices constants, handler protocols, `Unimplemented...` handler bases,
  dispatch tables and typed call methods are generated by `tools/gen` from the
  schemas, the appendices CSVs and the tables in `tools/gen/profiles.py` (blocks,
  directions, handler names, spec-text rules, one-way messages). The `CSMS`,
  `ChargePoint`/`ChargingStation` and `Config` classes are hand-written.
- Generated files start with `# Code generated by tools/gen. DO NOT EDIT.`, are
  committed, and `tests/unit/test_generated_up_to_date.py` fails if they drift.
  Fix the generator, never the output.
- Names: strip the schema's `Type` / `EnumType` suffix (`IdTokenType` → `IdToken`);
  an enum whose name an object already has keeps `Enum` (`IdTokenEnum`). Class
  names otherwise keep the spec's spelling so users can search the spec.
- Request/response naming follows each spec: 1.6 `<Action>Request` /
  `<Action>Confirmation`; 2.0.1 and 2.1 `<Action>Request` / `<Action>Response`.
  The 2.1 SEND message `NotifyPeriodicEventStream` has no `Request` suffix (the
  spec names it so).
- The action name is a `ClassVar` (`ACTION`), so no field can clash with it.
- Enums are `enum.StrEnum`, values exactly as in the spec. `Celcius` and `Celsius`
  are both valid 1.6 `UnitOfMeasure` values (OCPP-J 1.6 errata 2025-04).
- Optional scalars/objects/timestamps are `X | None = None`. Optional arrays are
  `list[X] | None = None`: absent is fine, present must meet minItems/maxItems.
  A required string must be non-empty, except the allow-listed
  `SetVariableData.attributeValue`.
- Decimals are `float`. Properties without a type (DataTransfer `data`) are
  `Any` (any JSON value). `customData` keeps unknown vendor properties
  (`extra="allow"`).
- `v21` has its own types and does not import `v201`. A message unchanged from
  2.0.1 is still its own class, because `ocpp2.1` is a different subprotocol.

### Validation

- Validate on both send and receive. A malformed incoming CALL gets the correct
  CALLERROR, never a crash.
- **Unknown properties are ignored on decode** (`extra="ignore"`), although the
  schemas say `additionalProperties: false`: real charge points send extras and
  rejecting them would break interoperability. Everything else the schemas reject
  is rejected too; `tests/schema` proves it with mutation tests (break every
  required field, maxLength, enum, type, date-time, minItems/maxItems,
  minimum/maximum).
- Constraints from the spec text beyond the schemas are listed per profile in
  `tools/gen/profiles.py` and enforced in generated validators. Only clear,
  mechanically checkable statements (a conditional required field, a range, a
  syntax, "SHALL be > 0"); not "should", cross-message conditions, or conditions on
  device model variables. Carry over the rules go-ocpp-sdk enforces, including:
  - 1.6: `connectorId` ≥ 0 or > 0 as the spec says per message; `meterValue` 1..*;
    first charging period starts at 0; limits with at most one decimal;
    RemoteStartTransaction profile purpose must be TxProfile; `SendLocalList`
    idTags unique (case-insensitive) and `idTagInfo` on every entry of a Full
    update; `GetLocalListVersion` ≥ -1; `TriggerMessage.connectorId` > 0 when
    present; `GetDiagnostics`/`UpdateFirmware` locations are absolute URIs.
  - 1.6 security: `GetInstalledCertificateIds.conf` may have an empty
    `certificateHashData` (spec 0..* beats schema); `serialNumber` checked as hex
    only; certificates/CSRs checked as PEM blocks of the right type, not parsed.
  - 2.1 errata 2026-09: `pctMaxDischargePower` is required (2.28);
    `PowerMonitoringMustTrip` is refused as a stand-alone DER control (2.30); in
    the OCPP-J part 4 example of NotifyPeriodicEventStream, `t` is a number and
    `basetime` is required (4.2).
- Not enforced (same as Go): the printable-ASCII character set of 1.6
  `CiString`/`String` and 2.x `identifierString`/`string` — only lengths.

### Date-times

- One implementation in `ocpp_sdk.datetime` for every version.
- Send UTC with `Z`, whole seconds, or milliseconds when present.
- Accept RFC 3339 with/without fractional seconds, `Z` or offsets, and no zone
  (taken as UTC) — set by the owner. Naive `datetime` objects passed in by callers
  are rejected with a clear error.

### Framing (`ocppj`) — same behaviour as go-ocpp-sdk

- Unreadable message ID is answered with `-1` (2.0.1 OCPP-J 4.2.3).
- Unknown message type: `MessageTypeNotSupported` in 2.0.1; ignored in 1.6 and 2.1
  (2.1 errata 2026-09, part 4, 4.1/4.3).
- A `null` payload is accepted and treated as `{}`.
- Message IDs ≤ 36 characters.
- The endpoint is transport-agnostic (the transport gives it a send callable and
  feeds incoming frames). Defaults: 30 s response timeout counted from send;
  one outstanding CALL per direction per connection; bounded queue of 1,000 calls.
  A caller that is cancelled or times out frees the outstanding slot so the queue
  keeps moving; late responses are dropped.
- Incoming CALLs run in their own task so a handler may call back into the peer.
- 2.1 only: SEND (`[6, ...]`) and CALLRESULTERROR (`[5, ...]`), OCPP-J 2.1 part 4
  4.1.3, 4.2.3, 4.2.4. Elsewhere they are unknown message types. A SEND is not
  queued behind CALLs, may be sent while a CALL is outstanding, is never answered
  (a malformed or unknown SEND is only logged); incoming SENDs are handled on one
  task per endpoint in arrival order with the same queue bound (newest dropped when
  full). A CALLRESULT that cannot be decoded is answered with a CALLRESULTERROR.

### Transport — same behaviour as go-ocpp-sdk

- Server: charge point ID from the last URL path segment; ID ≤ 48 chars, no `:`
  or `/`. Unknown ID → 404, bad credentials → 401, failed certificate identity → 403.
- Version is chosen by the server's preference order among the client's offered
  subprotocols (`ocpp1.6`, `ocpp2.0.1`, `ocpp2.1`). A mismatch completes the
  handshake without a subprotocol and then closes with 1002 (OCPP-J §3.2).
- A second connection for the same ID replaces the old one (old closed with 1008).
- TLS ≥ 1.2 with the spec's GCM suites (plus ECDHE-RSA GCM); TLS 1.0/1.1 are not
  supported. Profile 3 requires subject CN == charge point ID and optionally O
  containing the operator name (A00.FR.404/405/511).
- 1.6 Basic-auth password is the `AuthorizationKey` (16–20 bytes as 32–40 hex
  digits, sent as that text); provide `check_authorization_key` /
  `generate_authorization_key`.
- WebSocket compression disabled; binary frames rejected. Defaults: ping 30 s,
  pong timeout 10 s, max message 1 MiB.
- Client reconnect per OCPP-J §5.4 with the spec's names (`wait_minimum`,
  `random_range`, `repeat_times`), defaults 1 s / 2 s / 6 doublings. The wait
  applies after every lost connection and failed attempt; a missing common
  subprotocol counts as a failed attempt.
- Graceful shutdown: a connection whose handshake completes after shutdown started
  is closed with 1001 as it registers (go-ocpp-sdk bug fixed after v0.1.0 — add a
  test for it).

### High-level API

- Charge point side: typed async methods, e.g.
  `await cp.boot_notification(BootNotificationRequest(...))` →
  `BootNotificationConfirmation`. Each call accepts an optional `timeout=`.
- Handlers: one handler protocol per profile (1.6) or functional block (2.x) that
  has messages the side receives, with a generated `Unimplemented<Name>Handler`
  base that answers `NotSupported`. Wiring is one optional field per
  profile/block in a `Config` dataclass; `None` answers `NotSupported`. An action
  the SDK does not know answers `NotImplemented`. Blocks with nothing to receive
  on a side have no field there. Handlers may be sync or async.
- CSMS handlers receive the `ChargePoint` session object so they can call the
  station back. A session object is tied to one connection.
- A handler that raises is answered with `InternalError`; the exception text is
  never sent to the peer. Raise `ocpp_sdk.errors.CallError` to send a specific
  code and description.
- CSMS: `charge_point_ids()`, `for_each(fn)` (visits connected stations in
  identity order), typed async methods to call a station by ID, `shutdown()`.
- Clients and servers are async context managers. `close()` uses the close
  handshake's own short timeout; `CSMS.shutdown(timeout=...)` takes one.
- **Offline behaviour:** calls fail fast with `NotConnectedError` (also a call
  interrupted by a lost connection); nothing is queued or retried by the SDK; the
  station never sends BootNotification or Heartbeat on its own.
- **1.6 transaction message queue** (spec section 3.7), opt-in and separate from
  `ChargePoint`: the application hands StartTransaction, StopTransaction and
  MeterValues to it; it delivers oldest first, waits while offline without
  counting that as a failure, retries what the Central System fails to process
  (CALLERROR, timeout, unusable answer) up to `attempts` times waiting
  `retry_interval` × earlier attempts, then drops it (`on_discard`). A
  StartTransaction queued offline returns a `Transaction` handle; messages queued
  with it get the assigned transactionId and are dropped if the start was
  dropped. Persistence via a `TransactionStore` protocol with an in-memory
  default and a `FileStore` (atomic JSON file), no extra dependency.
- Shared lifecycle code for the versions' CSMS and station classes lives in
  `_internal`; public classes must not expose internal types.

### Code quality

- Every I/O call is `async`. Background tasks are owned by a `TaskGroup` or
  tracked and cancelled on close; never fire-and-forget.
- Exceptions from `ocpp_sdk.errors`: `OCPPError` base; `CallTimeoutError`,
  `NotConnectedError`, `CallError` (received or to send), `ValidationError`. Never
  use bare `except:`; chain with `raise ... from`.
- Logging: `logging.getLogger("ocpp_sdk.<module>")`; never configure handlers in
  library code; never log at import time.
- Everything public is typed and has a Google-style docstring with a short
  example; anything not re-exported or documented is private (`_` prefix).
- Tests that build and run examples or need many connections are marked
  `@pytest.mark.slow` and skipped with `-m "not slow"`.
- **Test coverage (mandatory):** line and branch coverage MUST NEVER fall below
  **95%**, measured per package (each directory under `src/ocpp_sdk`, not just in
  total), and every critical path MUST be covered. Critical paths are: frame
  parsing and serialization, every error and CALLERROR path, validation of
  required fields/lengths/enums on send and receive, timeouts, cancellation,
  disconnects, reconnects, queueing and ordering, authentication and TLS handling,
  and concurrent use. A change that drops any package below 95% is not done; add
  tests, never lower the threshold or add `pragma: no cover` to pass it. Only
  `examples/` and test-support code are exempt. `scripts/coverage.py` enforces
  this and CI runs it.

## 5. Commands

Run after every change, and fix failures before moving on:

```bash
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests tools
uv run pytest --cov=ocpp_sdk --cov-branch --cov-report=json
uv run python scripts/coverage.py   # fails if any package is below 95%
```

Regenerate after changing the generator, its tables, or the schemas (the
up-to-date test fails when the committed files are stale):

```bash
uv run python -m tools.gen && uv run ruff format src/ocpp_sdk
```

## 6. How to work

1. At the start of a session, read this file and find the first unchecked item in
   the Roadmap. Work on that item only.
2. Before starting a new **phase**, post a short plan (files, public API sketch,
   open questions) and wait for the owner's OK.
3. Work in small steps. After each step: run the commands in section 5, then commit.
4. Commit messages: `<area>: <what changed>` e.g. `ocppj: parse CALLERROR frames`.
   One logical change per commit. **No AI attribution trailers** (no
   `Co-Authored-By` lines) — owner's request.
5. When an item is done, tick its checkbox in this file in the same commit.
6. Record any design decision or deviation from the spec in "Decisions" below.
7. Stop and ask the owner when: the spec is unclear, a new runtime dependency is
   needed, the public API of the high-level classes needs to change after it was
   agreed, a test cannot be made to pass without changing agreed behaviour, or
   you want to differ from a go-ocpp-sdk decision in section 4.
8. Keep the documentation site in sync (section 10): any change that adds, removes
   or alters public API, behaviour, supported messages, configuration, errors or
   roadmap status MUST update `site/` and README.md in the same commit.
9. Never delete or weaken a test to make it pass, never edit generated files by
   hand, and never lower the 95% coverage threshold.
10. Releases: tag locally only with the owner's OK; the owner pushes `main` and the
    tag after CI and Pages have run. PyPI publishing runs from the tag.

## 7. Roadmap

### Phase 0 — Setup

- [x] `pyproject.toml` (name `ocpp-sdk`, package `ocpp_sdk`, Python >=3.11,
      hatchling, ruff/mypy/pytest/coverage config; `docs/spec/` excluded from
      sdist and wheel), `src/ocpp_sdk/__init__.py`, `py.typed`
- [x] `README.md` stub, `LICENSE` (confirm MIT with owner), `.gitignore`
- [x] `scripts/coverage.py` (95% per package)
- [x] CI `ci.yml`: format check, lint, mypy, pytest + coverage script on a
      matrix of Python 3.11 → latest, on push and PR
- [x] `site/index.html` skeleton and `pages.yml` publishing only `site/`
- [x] `docs/spec/README.md` listing which spec files are expected there

### Phase 1 — Core (`errors`, `datetime`, `ocppj`)

- [x] Exception hierarchy, `CallError`, `ErrorCode` sets for 1.6 and 2.0.1/2.1
      (note spelling differences)
- [x] `ocpp_sdk.datetime` (section 4 rules)
- [x] `ocppj.frames`: CALL `[2, id, action, payload]`, CALLRESULT `[3, id, payload]`,
      CALLERROR `[4, id, code, description, details]`; message IDs ≤ 36 chars
- [x] `ocppj.registry`: action → request/response models per version
- [x] `ocppj.endpoint`: correlation, timeouts, one outstanding CALL per direction,
      bounded queue, cancellation frees the slot, incoming CALLs in own task,
      framing rules from section 4
- [x] Parametrised tests: valid frames, malformed JSON, wrong element types,
      unknown action, unknown message type, unreadable ID, null payload,
      response with unknown ID, timeout, cancellation, queue full

### Phase 2 — Transport

- [x] Pick the WebSocket library (`websockets` is the default choice; record
      the decision and why in Decisions; owner approves)
- [x] Server: ID from URL, ID rules, connection registry, connect/disconnect
      callbacks, duplicate ID replaces old (1008)
- [x] Subprotocol negotiation by server preference; mismatch → close 1002
- [x] Client with OCPP-J §5.4 reconnect
- [x] Ping/pong keep-alive, max message size, compression off, binary rejected
- [x] Security profile 1: Basic Auth (charge point ID as username)
- [x] Security profile 2: TLS ≥ 1.2 + Basic Auth (`ssl.SSLContext`)
- [x] Security profile 3: mTLS with CN/O identity checks
- [x] Graceful shutdown, including the late-handshake case (close 1001)
- [x] Tests: handshake, mismatch, 401/403/404, reconnect timing, duplicate ID,
      concurrent connections, shutdown

### Phase 3 — Generator and OCPP 1.6 models

- [x] `tools/gen` reading schemas + `profiles.py`; generated-file header;
      up-to-date test
- [x] Generated 1.6 types, enums and messages for all six feature profiles
      (28 messages), with the 1.6 spec-text rules from section 4
- [x] Round-trip test for every message with sample payloads
- [x] Schema mutation tests against the official 1.6 schemas (`tests/schema`)

### Phase 4 — High-level API for 1.6

- [ ] Post the API sketch for `v16.charge_point` and `v16.csms` and wait for OK
- [ ] Generated handler protocols, `Unimplemented...` bases, dispatch and typed
      calls for 1.6
- [ ] `ChargePoint` and `CSMS` classes, `Config` wiring, error/handler rules,
      offline behaviour (section 4)
- [ ] Integration test (in-process): BootNotification → StatusNotification →
      Authorize → StartTransaction → MeterValues → StopTransaction,
      plus RemoteStartTransaction and Reset from the CSMS
- [ ] Tests for timeout, disconnect mid-call, reconnect, `NotSupported` /
      `NotImplemented` / `InternalError` answers

### Phase 5 — Remaining 1.6 profiles in the high-level API

- [ ] Firmware Management, Local Auth List Management, Reservation,
      Smart Charging, Remote Trigger wired into both sides; tests for each
- [ ] 1.6 transaction message queue (`transaction_queue.py`) with in-memory and
      file stores

### Phase 6 — 1.6 examples, docs, release

- [ ] `examples/v16/csms.py` and `examples/v16/charge_point.py` (plain `ws://`,
      optional Basic auth) and a slow smoke test running them against each other
- [ ] Interop test: Python CSMS ↔ go-ocpp-sdk v1.1.0 1.6 charge point and the
      reverse (`go run github.com/foecum/go-ocpp-sdk/examples/v16/...@v1.1.0`;
      CI installs Go; marked slow)
- [ ] README and `site/`: install, quick start for both roles, supported messages
      table, security profiles, logging, error handling
- [ ] `release.yml`: `uv build`, `twine check`, publish to PyPI with trusted
      publishing on tag push (owner sets up the PyPI side)
- [ ] Tag `v0.1.0` (ask owner first)

### Phase 7 — OCPP 1.6 security extension

- [ ] Generated `v16/security`: SecurityEventNotification, SignCertificate,
      CertificateSigned, InstallCertificate, DeleteCertificate,
      GetInstalledCertificateIds, ExtendedTriggerMessage, GetLog,
      LogStatusNotification, SignedUpdateFirmware, SignedFirmwareStatusNotification;
      clashing enums renamed (`SignedFirmwareStatus`, `ExtendedMessageTrigger`,
      `SignedUpdateFirmwareStatus`); `is_known_event` / `is_critical_event`
- [ ] `Security` field in both `Config`s; AuthorizationKey helpers
- [ ] Tests, site update

### Phase 8 — OCPP 2.0.1

- [ ] Post a plan for 2.0.1 and wait for OK
- [ ] Block table and direction table in `profiles.py` (64 messages: 24 from the
      station, 39 from the CSMS, DataTransfer both)
- [ ] Generated `v201/types.py` and one module per functional block:
  - [ ] A Security  - [ ] B Provisioning  - [ ] C Authorization
  - [ ] D Local Authorization List  - [ ] E Transactions  - [ ] F Remote Control
  - [ ] G Availability  - [ ] H Reservation  - [ ] I Tariff and Cost
  - [ ] J Meter Values  - [ ] K Smart Charging  - [ ] L Firmware Management
  - [ ] M ISO 15118 Certificate Management  - [ ] N Diagnostics
  - [ ] O Display Message  - [ ] P Data Transfer
- [ ] Spec-text rules for 2.0.1 in `profiles.py`
- [ ] Generated `v201/appendices.py` (components, variables, units, reason codes,
      security events) as string constants; messages keep plain strings
- [ ] Generated handlers; `ChargingStation`, `CSMS`, `Config` for 2.0.1
- [ ] Schema mutation tests for every message
- [ ] Integration test: boot, authorize, TransactionEvent (Started/Updated/Ended),
      RequestStartTransaction from CSMS, GetVariables/SetVariables
- [ ] `examples/v201/*` with smoke test; interop test against go-ocpp-sdk 2.0.1
- [ ] README and site update; tag `v0.2.0` (ask owner first)

### Phase 9 — Hardening

- [ ] Hypothesis property tests: frame parsing, registry decode, endpoint frame
      handling, date-times, decode of every message (no crash; accept-then-
      roundtrip consistency). `fuzz.yml` runs them with a large example count
      weekly and on demand; failing examples are added as explicit test cases
- [ ] Benchmarks (`pytest-benchmark`) for framing, decode and a CSMS with many
      stations; results in `docs/benchmarks.md`, labelled with the machine,
      no CI thresholds
- [ ] `examples/loadtest`: in-process CSMS + N stations over loopback for 1.6 and
      2.0.1; ops/s and latency percentiles; 20-station slow smoke test;
      1,000-station run is manual
- [ ] API review in `docs/api-review.md`, owner approves; `CHANGELOG.md`
- [ ] Tag `v1.0.0` (ask owner first). From here breaking changes need a new major
      version.

### Phase 10 — OCPP 2.1

- [ ] Post a plan for 2.1 and wait for OK
- [ ] `ocppj`: SEND and CALLRESULTERROR on 2.1 connections (section 4)
- [ ] Generator profile for 2.1: 91 messages (the 64 of 2.0.1 plus 27), 19 blocks:
      the 16 of 2.0.1 plus Q `bidirectional`, R `dercontrol`, S `batteryswap`;
      directions of the 27 new messages read from the part 2 scenarios (match
      go-ocpp-sdk's `internal/gen/profiles.go`)
- [ ] Generated `v21` types, blocks, appendices (also idToken types, connector
      types, charging limit sources, payment brands and recognitions,
      additionalInfo types, signing methods), handlers; 2.1 spec-text and errata
      rules
- [ ] `ChargingStation` (incl. `notify_periodic_event_stream`), `CSMS`, `Config`
      (incl. `send_handler`) for 2.1
- [ ] Examples, load test, property tests and benchmarks for 2.1; interop test
      against go-ocpp-sdk 2.1
- [ ] README and site update; tag `v1.1.0` (ask owner first)

## 8. Decisions

Record each decision as: date — decision — reason.

- 2026-11-26 — PyPI name `ocpp-sdk`, import name `ocpp_sdk` — `ocpp` is taken on PyPI.
- 2026-11-26 — Async-first on `asyncio`, Python 3.11+ — needed for `TaskGroup`
  and `asyncio.timeout`.
- 2026-11-26 — All message models are Pydantic v2, generated from the official
  schemas (including 1.6). Pydantic tells a missing field from a zero value, so
  the Go `ocpp:"required"` raw-JSON check is not needed.
- 2026-11-26 — Protocol behaviour follows go-ocpp-sdk v1.1.0 (section 4); any
  deviation needs the owner's OK and an entry here.
- 2026-11-26 — Documentation is a self-contained static site in `site/` (no build
  step), as in go-ocpp-sdk, instead of a generated docs site.

- 2026-11-26 — Owner: do not ask for approval before each phase; proceed through the
  roadmap and ask only clarifying questions (overrides 6.2 "wait for the owner's OK").
- 2026-11-26 — Added `ocpp_sdk/versions.py` (`Version` StrEnum = subprotocol names),
  used by errors, frames, registry and endpoint.
- 2026-11-26 — Frame-level errors (not JSON, not an array, bad element types,
  unreadable id) answer `FormationViolation` (1.6) / `RpcFrameworkError` (2.x). Spec
  PDFs are not in `docs/spec/` yet, so this is from memory of OCPP-J; re-check when
  the specs are added. Re-checked against the 1.6 and 2.0.1 OCPP-J specs: `FormationViolation`
  (1.6) and `RpcFrameworkError` (2.0.1, "MessageId could not be read") are right. A message id over 36 characters counts as unreadable (`-1`).
- 2026-11-26 — A CALLERROR with four elements (no details) is accepted; real stations
  omit it. Malformed CALLRESULT/CALLERROR frames are never answered; if the id
  matches the outstanding call, that call fails with `ValidationError`.
- 2026-11-26 — Pydantic error → CALLERROR code: missing / too_short / too_long →
  `OccurrenceConstraintViolation`; wrong JSON type → `TypeConstraintViolation`;
  everything else (length, enum, range, date-time) → `PropertyConstraintViolation`.
  Only the field path and error type are sent, never the offending value.
- 2026-11-26 — `Endpoint.feed()` is synchronous (it only schedules tasks); the queue
  limit counts calls not yet picked up by the sender, so with the default of 1,000
  at most 1,001 calls can be in flight. Added `QueueFullError` to `errors`.
- 2026-11-26 — pytest runs doctests (`--doctest-modules`) over `src` too, so the
  examples in docstrings stay correct.

- 2026-11-26 — WebSocket library: `websockets` (new asyncio implementation, >=14),
  approved by the owner: mature, supports subprotocol selection hooks, HTTP-level
  `process_request` for 401/403/404, ping/pong, size limits and compression off.
  Dev-only: `trustme` generates test certificates.
- 2026-11-26 — Transport hands frames to a `FrameSink` protocol (`feed` + `close`),
  which `ocppj.Endpoint` satisfies; added `transport/connection.py` for `Connection`
  and `FrameSink`. `Server(on_connect)` / `Client(url, on_connect)` build the sink per
  connection. Order of handshake checks: ID (404) → certificate identity (403) →
  Basic auth (401).
- 2026-11-26 — Graceful shutdown closes existing connections (1001) and waits for
  their handlers *before* the listener stops, so a handshake that finishes during
  shutdown reaches our handler and is closed with 1001 (websockets itself would
  answer 503 once the listener is closed). `close_timeout` defaults to 5 s.
- 2026-11-26 — 1.6 models are generated from `docs/spec/1.6/schemas/json` (draft-04,
  inline enums and objects, no `$ref`). The schemas name nothing, so `profiles.py` maps
  each schema location to a class or enum name (go-ocpp-sdk's names; spec spelling such as
  `ChargingProfilePurposeType`). The generator fails on an unnamed enum/object, an
  unsupported schema keyword, a schema in no module (the security extension is listed as
  `deferred` until phase 7) or a table entry that matches nothing.
- 2026-11-26 — Generated code goes through `ruff check --fix --select I,F401` and
  `ruff format` inside the generator, so the files equal what `ruff format` produces and
  the up-to-date test can compare text. `python -m tools.gen` alone is enough.
- 2026-11-26 — Strict scalars (`StrictInt`/`StrictStr`/`StrictBool`, `Number` that
  accepts ints but not bools or strings): JSON `1.0` is not an integer and `"5"` is not a
  number. `DateTime` parses with `ocpp_sdk.datetime` and sends UTC with `Z`. Spec-text rules
  are Python statements in `profiles.py` run by one generated `model_validator`; they raise
  `rule_error(path, reason)` / `needed_error(path)` (pydantic custom errors `ocpp_rule` /
  `ocpp_needed` carrying the field path), which the registry reports with the full path and
  maps to `PropertyConstraintViolation` / `OccurrenceConstraintViolation`.
- 2026-11-26 — The 1.6 `DataTransfer.data` is a string in the 1.6 schemas (AGENTS section 4
  says properties without a type are `Any`; that applies to the 2.x schemas where `data` has no
  type). `docs/spec/go.mod` (Go-only) and the Go copies `docs/api-review.md` and
  `docs/benchmarks.md` are not committed.
- 2026-11-26 — A JSON `null` for an optional field is accepted and read as absent (as
  go-ocpp-sdk does); `null` for a required field or array item is rejected. The schemas
  forbid null everywhere, so the mutation tests do not try it on optional fields.
- 2026-11-26 — Client `__aenter__` waits for the first connection (with reconnect
  enabled it keeps retrying; use `start()` + `wait_connected(timeout)` to bound it).

## 9. Known gaps / skipped spec items

List anything not implemented or simplified, with a reason. Gaps inherited by
design from go-ocpp-sdk:

- String character sets (1.6 `CiString`/`String`, 2.x `identifierString`/`string`)
  are not enforced, only lengths, because real stations send other characters.
- TLS 1.0/1.1, which the 1.6 security whitepaper tolerates for old stations, are
  not supported.
- 2.0.1/2.1 field tables say some arrays are 0..* where the schema says
  `minItems` 1: an absent array is accepted, a present one must have an element.
- 2.1 tariff cost calculation and dynamic schedule rules are application
  behaviour; the SDK only validates and transports the messages.

## 10. Documentation site

User-facing documentation is a static HTML site in `site/` (entry point
`site/index.html`), published to GitHub Pages by `.github/workflows/pages.yml`.
Only `site/` is published, never `docs/spec/`.

- **Update `site/` every time a change adds something users need to know**: new or
  changed public API, new modules, supported messages (keep the supported-messages
  table accurate), configuration options, exceptions and how to handle them,
  security profiles, behaviour changes, and roadmap/status changes. Do it in the
  same commit as the code, and update README.md accordingly.
- Every code sample on the site must run against the current API. Check samples
  before committing (run them from a scratch file, then delete it), or keep them
  as doctests that the test suite runs.
- Document only what exists. Anything planned is labelled "planned" and must not
  look usable. Bump the status table when a roadmap phase completes.
- Keep it self-contained: one HTML file plus assets in `site/`, no build step, no
  external scripts; system fonts only. It must work in light and dark mode and on
  phone widths.
- Before merging a docs-affecting change, open `site/index.html` in a browser and
  check it renders correctly.
