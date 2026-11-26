# python-ocpp-sdk

Async Python SDK for **OCPP-J** (OCPP over JSON/WebSocket), covering the Charge
Point / Charging Station and Central System / CSMS roles.

**Status: pre-alpha, under construction.** The core (errors, date-times, OCPP-J
framing, endpoint) and the WebSocket transport (server, client with reconnect,
security profiles 1-3) are done; the OCPP message models and high-level
`ChargePoint`/`CSMS` APIs are not, so it cannot be used to build a station or
CSMS yet. See the documentation site (`site/index.html`).

| Version   | Status  |
|-----------|---------|
| OCPP 1.6J | planned |
| OCPP 2.0.1 | planned |
| OCPP 2.1  | planned |

- PyPI name: `ocpp-sdk` (import `ocpp_sdk`), Python 3.11+
- Sister project: [go-ocpp-sdk](https://github.com/foecum/go-ocpp-sdk)
- Licence: MIT
