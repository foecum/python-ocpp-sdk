# python-ocpp-sdk

Async Python SDK for **OCPP-J** (OCPP over JSON/WebSocket), covering the Charge
Point / Charging Station and Central System / CSMS roles.

**Status: pre-alpha, under construction.** The core (errors, date-times, OCPP-J
framing, endpoint), the WebSocket transport (server, client with reconnect,
security profiles 1-3) and the OCPP 1.6 message models (generated from the official
schemas) and the high-level OCPP 1.6 `ChargePoint` and `CSMS` classes (typed calls,
handlers per feature profile) are done, so 1.6 stations and Central Systems can be
built, with an opt-in transaction message queue (in-memory or file-backed) and
examples in `examples/v16`. The 1.6 security extension messages and AuthorizationKey helpers are in too. OCPP 2.0.1 is done too (`ocpp_sdk.v201`, examples in `examples/v201`). 2.1 is not done. See the documentation site (`site/index.html`).

| Version   | Status  |
|-----------|---------|
| OCPP 1.6J | models, high-level API, transaction queue, examples, go-ocpp-sdk interop tests and the security extension done |
| OCPP 2.0.1 | done: 64 messages, appendices constants, `ChargingStation` and `CSMS` |
| OCPP 2.1  | planned |

## Quick start

```bash
python examples/v16/csms.py --port 9000                                  # Central System
python examples/v16/charge_point.py --url ws://127.0.0.1:9000/CP-1       # Charge Point
python examples/v201/csms.py --port 9001                                 # OCPP 2.0.1 CSMS
python examples/v201/charging_station.py --url ws://127.0.0.1:9001/CS-1  # 2.0.1 station
```

See `site/index.html` for the API: typed calls, handlers per feature profile, security
profiles 1-3, the transaction queue, logging and error handling.

- PyPI name: `ocpp-sdk` (import `ocpp_sdk`), Python 3.11+
- Sister project: [go-ocpp-sdk](https://github.com/foecum/go-ocpp-sdk)
- Licence: MIT
