# Current status

2026-10-22: First implementation complete. Scope is one real HTTP/SQLite response-loss experiment, with plain and idempotent modes and replay generated from recorded events.

Local Python 3.12 cannot create sockets (`PermissionError: Operation not permitted`). Local database and conversion tests will run here; mandatory HTTP/process tests and the demonstration must pass in GitHub Actions before completion. Do not replace them with mocks or skip them.

17 tests now cover the experiment. Locally, 11 database/replay/output-safety tests pass; 6 HTTP/process tests remain blocked by socket permissions. Compilation passes. Independent review identified and closed one event timestamp ordering issue under write-lock contention; its controlled concurrency regression passes.

Next: publish to Albus-Hedwig/reliability-lab, run mandatory Linux/macOS CI, inspect actual generated evidence and verify replay in a browser. No HTTP success or observed example is claimed until CI completes.
