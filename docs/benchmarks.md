# Benchmarks

Indicative numbers, not guarantees. They were measured once on one machine and vary with
hardware, load and Python version; compare runs on the same machine only. There are no pass or
fail thresholds in CI.

- Machine: 11th Gen Intel Core i7-11370H (8 logical CPUs), Linux 6.12 (amd64)
- Python 3.14.7, pydantic 2, websockets 17
- Date: 2026-11-27 (2.1 rows added the same day)

Run them yourself (normal test runs only execute each benchmark once, to check it works):

```bash
uv run pytest tests/benchmarks --benchmark-enable --benchmark-only
uv run python examples/loadtest/loadtest.py --version 16 --stations 20 --seconds 10
```

## Framing and decoding (mean time per operation)

| Benchmark | Mean |
|---|---|
| parse a CALL frame (`BootNotification`) | 3.4 µs |
| encode a CALL frame | 2.8 µs |
| 1.6 decode `BootNotification` | 1.3 µs |
| 1.6 decode `StartTransaction` | 2.3 µs |
| 1.6 decode `MeterValues` (one sampled value) | 4.0 µs |
| 2.0.1 decode `BootNotification` | 3.0 µs |
| 2.0.1 decode `NotifyReport` (full sample) | 8.5 µs |
| 2.0.1 decode `TransactionEvent` (full sample) | 11.5 µs |
| 2.1 decode `BootNotification` | 3.0 µs |
| 2.1 decode `NotifyPeriodicEventStream` (a SEND) | 3.5 µs |
| 2.1 decode `TransactionEvent` (full sample, with cost details) | 30 µs |
| 2.1 decode `SetChargingProfile` (full sample, V2X curves) | 39 µs |
| 1.6 encode `MeterValues` (validates again) | 9.0 µs |
| 2.0.1 encode `TransactionEvent` (validates again) | 22 µs |
| a complete call between two endpoints (no network) | 74 µs |

Encoding validates the message again on purpose (a model changed after creation must not reach
the wire), which is why it costs more than decoding. A real station sends a message every few
seconds, so none of this matters until a CSMS serves a very large fleet.

## A CSMS with many stations (loopback, one process)

| Benchmark | Mean |
|---|---|
| 50 stations each send one Heartbeat at once | 4.6 ms |

## Load test (`examples/loadtest`)

An in-process CSMS and N stations on loopback WebSockets. Each station boots, then sends
Heartbeat and MeterValues (1.6) or TransactionEvent (2.0.1 and 2.1) one after the other. Both sides run
in the same Python process on one core, so the throughput is the work for *both* ends.

| Run | Calls/s | Latency p50 / p95 / p99 / max |
|---|---|---|
| 1.6, 20 stations, 5 s | 10,300 | 1.9 / 2.5 / 3.2 / 4.4 ms |
| 2.0.1, 20 stations, 5 s | 9,700 | 2.0 / 2.6 / 3.9 / 4.9 ms |
| 2.1, 20 stations, 4 s | 10,500 | 1.9 / 2.2 / 2.8 / 4.4 ms |
| 1.6, 1,000 stations, 20 s | 7,200 | 128 / 175 / 229 / 274 ms |
| 2.0.1, 1,000 stations, 20 s | 6,600 | 144 / 189 / 241 / 254 ms |
| 2.1, 1,000 stations, 20 s | 7,500 | 127 / 147 / 228 / 238 ms |

With 1,000 stations the latency is queueing: every station keeps one call in flight, so 1,000
calls share one core. The 1,000-station run is manual (`ulimit -n 8192`); the test suite runs a
20-station, 2-second smoke test (`tests/integration/test_loadtest.py`, marked slow).
