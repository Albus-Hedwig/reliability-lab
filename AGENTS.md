# reliability-lab

One experiment: an HTTP order service commits to SQLite, deliberately closes the connection before sending a response, and receives a retry. Compare plain inserts with transactionally enforced idempotency.

- Python 3.11+ standard library only. Run from the checkout with `python3 -m reliability_lab`.
- SQLite is the source of orders and ordered events. JSONL, summary and replay files are derived exports from a finished run, never independent scripted outcomes.
- Keep real HTTP integration tests mandatory. A restricted environment is a reported limitation, not a reason to mock or skip these tests.
- Bind the lab server to loopback only. Fault controls are lab-only and must never be described as production middleware.
- Preserve the upstream MIT notice in the vendored animation player. Record its origin in THIRD_PARTY_NOTICES.md.
- Keep current progress, verification evidence and remaining work in PROGRESS.md. Read it before resuming.

Validation: `python3 -m unittest discover -s tests -v`; `python3 -m reliability_lab --output runs/demo`. Keep generated runs out of Git except an explicitly selected example under examples/.
