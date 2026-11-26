# python-ocpp-sdk

Async Python SDK for **OCPP-J** (OCPP over JSON/WebSocket), covering the Charge
Point / Charging Station and Central System / CSMS roles.

**Status: pre-alpha, under construction.** The core (errors, date-times, OCPP-J
framing, endpoint), the WebSocket transport (server, client with reconnect,
security profiles 1-3) and the OCPP 1.6 message models (generated from the official
schemas) and the high-level OCPP 1.6 `ChargePoint` and `CSMS` classes (typed calls,
handlers per feature profile) are done, so 1.6 stations and Central Systems can be
built, with an opt-in transaction message queue (in-memory or file-backed). Examples,
the security extension, 2.0.1 and 2.1 are not done. See the documentation site (`site/index.html`).

| Version   | Status  |
|-----------|---------|
| OCPP 1.6J | models, high-level API and transaction queue done; examples, security extension planned |
| OCPP 2.0.1 | planned |
| OCPP 2.1  | planned |

- PyPI name: `ocpp-sdk` (import `ocpp_sdk`), Python 3.11+
- Sister project: [go-ocpp-sdk](https://github.com/foecum/go-ocpp-sdk)
- Licence: MIT
