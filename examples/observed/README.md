# Observed response-loss experiment

These files are the unmodified `experiment-ubuntu-latest` artifact from [GitHub Actions run 39747027407](https://github.com/Albus-Hedwig/reliability-lab/actions/runs/39747027407), recorded on 2026-10-22 at implementation commit `4350fa1bfa7b7b75c3eeebb8fca6b35e8eeba16c`.

Both Linux/Python 3.11 and macOS/Python 3.12 passed all 18 tests and ran the real HTTP experiment. This selected snapshot is the Linux run; process IDs, ports and durations belong to that host.

| Mode | Requests | Persisted orders | Returned order |
|---|---:|---:|---:|
| Plain | 2 | 2 | 2 |
| Idempotent | 2 | 1 | 1 |

Clone or download the repository and open `index.html` in a browser. GitHub's file viewer displays HTML source rather than executing it. Each scenario contains 11 recorded events and 11 replay steps. Playback slows each event to 1.5 seconds; `summary.json` contains the measured experiment durations.

The SQLite order counts, database events, JSONL exports, summary and replay step counts were checked for agreement after download. The artifact archive's SHA-256 was verified against GitHub's digest: `398e6c11f82a3fed952aa5006482966c112c4e7d356f4575a077800cb7eceb7a`.

The experiment uses only a synthetic SKU and a local loopback service. No external order or payment was created. Interactive browser playback was not manually verified in the authoring environment because its browser policy blocks local file URLs; automated conversion and HTML escaping tests passed.
