# reliability-lab

**An order commits. The response disappears. The client retries.**

真实 HTTP 请求、独立服务进程、SQLite 持久化：复现响应丢失后的重复订单，并用同一份执行记录生成离线回放。

[![Real HTTP experiment](https://github.com/Albus-Hedwig/reliability-lab/actions/workflows/test.yml/badge.svg)](https://github.com/Albus-Hedwig/reliability-lab/actions/workflows/test.yml)

The two runs send the same order and the same idempotency key. Only the service's persistence policy changes:

| Mode | HTTP attempts | Expected persisted orders | Retry behavior |
|---|---:|---:|---|
| Plain | 2 | **2** | Inserts another order |
| Idempotent | 2 | **1** | Returns the original order |

The runner checks these outcomes against the actual database. The replay derives its counts and steps from recorded events; it does not script the result shown in this table.

## Quick start

Requires **Python 3.11+**, Git, and permission to bind a loopback TCP socket. No Python packages, Docker, API keys, or external services are needed.

```bash
git clone https://github.com/Albus-Hedwig/reliability-lab.git
cd reliability-lab
python3 -m reliability_lab --output runs/demo
```

A successful run prints:

```text
plain        attempts=2 orders=2 response_order_id=2
idempotent   attempts=2 orders=1 response_order_id=1
Replay: .../runs/demo/index.html
```

Open `runs/demo/index.html` in your browser and choose a replay. The generated pages work offline. Run `python3 -m reliability_lab` without `--output` to create a fresh timestamped directory. An existing output directory is never overwritten.

## What actually happens

1. The runner starts an order service in a separate process on `127.0.0.1`, using an OS-assigned port.
2. The client sends `POST /orders` with a synthetic SKU and quantity.
3. The service commits the order to SQLite. The injected fault then closes the real TCP connection **before any HTTP status or response body is sent**.
4. The client observes a disconnected connection. The runner confirms that the first order exists before retrying.
5. The client sends the same request once more, with the same key and without the fault header.
6. The runner queries SQLite, verifies the outcome, and exports events and replays.

In idempotent mode, `BEGIN IMMEDIATE` serializes the lookup and insert, and a unique database constraint protects the key. The same key and payload return the same `201` body; a changed payload returns `409`. Orders and their persistence events commit in one transaction. Tests also exercise concurrent requests and rollback if recording the transactional event fails.

This is a controlled educational failure, not a simulation of arbitrary packet loss. It demonstrates an uncertain client outcome after a server-side commit. It does not claim exactly-once transport.

## Inspect the evidence

Each successful run contains:

```text
events.jsonl          # Combined export of the two recorded event streams
summary.json          # Queried outcomes, process IDs and measured run durations
index.html            # Comparison and evidence links
plain.html            # Offline replay of the plain run
idempotent.html       # Offline replay of the idempotent run
plain.json            # Diagram steps, each retaining its source event
idempotent.json
plain/
  lab.sqlite3         # Source of plain orders and events
  events.jsonl
  server.log
idempotent/
  lab.sqlite3         # Source of idempotent orders and events
  events.jsonl
  server.log
```

Query the databases with Python's SQLite module or a SQLite browser. The `orders` table holds business rows; `events` holds the globally ordered events within that run. Each scenario has its own database and sequence.

Recorded `time_ns` values use the host's monotonic clock at event recording time. They are not transaction flush timestamps or distributed-clock measurements. Replay holds each event for 1.5 seconds so you can read it; this playback speed is independent of measured execution time. `response_started` records the server's intention to write; only the client's `response_received` confirms receipt.

## Verify

```bash
python3 -m unittest discover -s tests -v
```

The suite includes mandatory real subprocess/HTTP tests, concurrent same-key requests, payload conflicts, malformed inputs, SQLite rollback, trace-to-replay consistency and HTML escaping. It does not skip socket tests when networking is unavailable. GitHub Actions runs the suite and records an experiment on Linux/Python 3.11 and macOS/Python 3.12; download the `experiment-*` artifacts from a successful run to inspect the complete evidence.

## Scope

- One synthetic order and one immediate retry. No payment provider, personal data, retry backoff, load generator, or external side effects.
- Loopback-only `http.server` with bounded JSON input. Its fault header deliberately interrupts responses; this is a lab service, not production middleware.
- SQLite idempotency applies while that database and key record are retained. This version does not implement expiry, authentication, multiple database nodes or external transaction coordination.
- The client writes its observations into the same local SQLite event log as the service. This is experiment instrumentation, not a proposed production telemetry design.

## Background

[Stripe's idempotent request documentation](https://docs.stripe.com/api/idempotent_requests) describes safely retrying operations after connection errors. [AWS's retry-with-backoff guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/retry-backoff.html) explains why retry behavior and idempotency must be considered together. This lab demonstrates one local failure case, not full compatibility with either service.

The offline renderer comes from [animate-architecture](https://github.com/Albus-Hedwig/animated-architecture-skill). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for its pinned source and MIT notice. The event conversion is specific to this lab.

## License

[MIT](LICENSE), including the preserved upstream notices in the vendored player and generated scenario pages.
