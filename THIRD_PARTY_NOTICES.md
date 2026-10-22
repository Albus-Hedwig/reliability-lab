# Animation player

`reliability_lab/_player/` contains these unmodified files from
[Albus-Hedwig/animated-architecture-skill](https://github.com/Albus-Hedwig/animated-architecture-skill),
release `v0.2.0` (commit `44120aa`), under `skills/animate-architecture/`:

- `scripts/build.py`
- `scripts/validate_diagram.py`
- `assets/player.template.html`
- `LICENSE`

The source files were unchanged in upstream commit `4939b7e` when vendored.
The complete upstream MIT copyright and license are preserved in
`reliability_lab/_player/LICENSE` and the HTML template (including generated HTML).
This project does not claim authorship of the player. The lab-specific event conversion
is in `reliability_lab/replay.py`.

To update, choose and record an upstream release/commit, copy these same four files
without modification, review their diff and license, then run the replay tests and
the browser verification of a real generated run. The browser verification tools
and optional dependencies from upstream are not vendored. Building and viewing
the lab replays requires no network fetch, CDN, or third-party Python package.
