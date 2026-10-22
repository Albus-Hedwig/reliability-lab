# Current status

2026-10-22: Implemented and published the first real HTTP/SQLite response-loss experiment at https://github.com/Albus-Hedwig/reliability-lab. Both modes use a separate service process, durable SQLite orders, an intentional TCP disconnect after commit, one retry, automated outcome checks and event-derived offline replay.

## Verification

- [CI run 39747027407](https://github.com/Albus-Hedwig/reliability-lab/actions/runs/39747027407), implementation `4350fa1bfa7b7b75c3eeebb8fca6b35e8eeba16c`: Linux/Python 3.11 and macOS/Python 3.12 each passed all 18 tests, with zero skips, then ran the actual CLI successfully. Both observed 2 requests / 2 orders in plain mode and 2 requests / 1 order with idempotency.
- The initial macOS run exposed reverse DNS blocking server startup. The loopback server now binds without DNS; the complete macOS suite dropped from 183 seconds with a startup failure to 0.772 seconds passing. A DNS-avoidance regression test was added.
- Independent review found and closed a timestamp ordering issue during SQLite write-lock contention. The controlled concurrency regression passes.
- Selected the successful Linux artifact under `examples/observed/`, verified its archive digest and checked SQLite rows/events against JSONL, summary and 11-step scenario replays. Provenance is in that directory's README.
- This local execution sandbox denies all socket creation. Database, conversion, output-safety and DNS-avoidance tests pass here; actual HTTP/process behavior was validated in CI without mocks or skips.

## Remaining limitation

The browser policy blocks local `file://` navigation, so interactive playback and visual layout were not manually verified here. Generated pages and source-event conversion pass automated tests. Open `examples/observed/index.html` after cloning to inspect playback. No production deployment, external effects, expiry policy or multi-node guarantees are included in this version.
