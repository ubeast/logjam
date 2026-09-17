# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync --extra dev                       # install core + test/lint deps
uv sync --extra dev --extra dashboard     # also the Streamlit UI

uv run pytest                             # full suite (tests/, in-memory DuckDB, network mocked via respx)
uv run pytest tests/test_analytics.py     # one file
uv run pytest -k opportunity              # one test by name
uv run ruff check .                       # lint (also: ruff format .)
uv run mypy src                           # type-check (strict)
```

`ruff` / `mypy` are strict everywhere **except** `scripts/reports/*.py` and
`scripts/build_pdfs.py`, which are exempt from the line-length rule (they embed
long prose, CSS, and HTML strings) — see `[tool.ruff.lint.per-file-ignores]`.

Runtime entry points: `uv run logjam <cmd>` (see `src/logjam/cli.py` docstring),
`uv run python scripts/refresh.py [--full]` (cron wrapper), and the brief
generators under `scripts/reports/`.

## Architecture

**One tidy table is the spine.** Every source — PortWatch, GDELT, and the AIS
adapter — reduces to long-format rows in `observation`, keyed
`(entity_type, entity_id, obs_date, metric, source)`. Baseline computation and
signal detection read that table and never know which source a row came from, so
adding a metric means writing an ingest adapter that emits the tidy shape and
nothing downstream changes. Schema lives in `src/logjam/store/db.py`
(`_SCHEMA_SQL`); three tables — `observation`, `baseline`, `signal`.

**The pipeline is one function.** `logjam.pipeline.refresh()` runs the whole
chain: ingest PortWatch → (optional GDELT) → reduce any pending AIS captures →
`compute_baselines` → `detect_bottlenecks` + `detect_congestion` →
`detect_opportunities`. It is idempotent — safe to re-run — because
`upsert_observations` does DELETE-then-INSERT on the natural key (PortWatch
revises its recent estimates, so re-ingesting an overlapping window must
overwrite, not append).

**Two baselines, computed per series** (`analytics/baseline.py`, stored as extra
columns on `baseline`):
- *short trailing* (robust median/MAD z over `baseline_window_days`) — catches a
  disruption's **onset**.
- *year-over-year* (same calendar date ±`yoy_halfwidth_days`, ~1 year back) —
  stays uncontaminated while an event is under a year old, so it answers "is this
  **still** abnormal or has it recovered?" after the short baseline has "healed"
  around the new low. This is why `logjam recovery` exists and why the briefs
  instead use a hard-coded pre-crisis window (see below).

**Detection sign convention:** every PortWatch metric is "more == more flow", so
a bottleneck is always the negative tail; opportunities look at the opposite
tail *within a substitution group* (`resources/substitution_groups.yaml`) — a
member running at/above its own baseline while another member of the same group
is bottlenecked.

**Config:** every tunable is a field on `logjam.config.settings`
(`src/logjam/config.py`), overridable via a `LOGJAM_`-prefixed env var or
`.env`. There is no other config file. `initial_backfill_days` must stay well
above `yoy_lag_days` or the YoY baseline is never populated.

### Source-specific notes

- **PortWatch** (IMF, keyless ArcGIS FeatureServer): the only source in the
  routine refresh. Weekly updates (Tue); under-reports the most recent ~2 weeks,
  which is why `recovery` and the briefs exclude/flag trailing days.
- **GDELT** (`ingest/gdelt.py`): news-attention per chokepoint. The DOC 2.0 API
  serves only ~90 days and throttles to ~1 req/5s, so it is a **collect-forward**
  source — `logjam news-fetch` is its own slow step (~2–3 min) and it is **off
  the `refresh` path by default** (`gdelt_on_refresh=False`). The store keeps
  history past the API window.
- **AISStream** (`ingest/aisstream.py`): a push WebSocket, *sampled* — connect
  for N minutes, capture position reports inside the zone bounding boxes
  (`resources/ais_zones.yaml`), then `ais-reduce` folds captures into
  `observation` as daily per-zone metrics. **The free feed is terrestrial AIS:
  no coverage in the Gulf / Red Sea / Arabian Sea** (exactly the briefs'
  geography). The adapter is complete and works against any European port; v1's
  geography needs a paid satellite-AIS feed.

### Reports subsystem (`scripts/reports/`)

Deliberately outside the `logjam` package. Each generator
(`hormuz_container_2026.py`, `suez_redsea_2026.py`, `horn_of_africa_2026.py`)
`sys.path`-inserts its own directory and imports the shared modules `_brief.py`
(query helpers + Markdown/HTML renderer + the SVG chart library, all `noqa: E402`)
and `_geo.py` (basemap + `map_point` for the map figures).

- A brief queries the **read-only** local DuckDB store, assembles a `payload`
  dict, writes it to `reports/data/<slug>.json` (the reproducible record), then
  hands `payload` + human-written narrative to the renderer. Prose is written by
  a person but **every number in it comes from `payload` via f-strings** — re-run
  after `logjam refresh` and the brief stays internally consistent.
- Briefs compare against a **fixed pre-crisis 2023 quarter**, hard-coded in each
  script — not the rolling baseline (by 2026 a rolling baseline treats the
  diverted level as normal). They need history past the default 900-day window:
  `LOGJAM_INITIAL_BACKFILL_DAYS=1400 uv run logjam refresh --full`.
- `scripts/reports/build_geo_assets.py` regenerates `src/logjam/resources/geo/`
  (basemaps + PortWatch coordinates); run once, needs `shapely` + network, output
  is committed. Basemaps: `mideast` (Hormuz brief), `corridor` (Suez),
  `redsea` (Horn).
- `scripts/build_pdfs.py` renders each brief `.html` and `docs/METHODOLOGY.md` to
  `.pdf` via **headless Google Chrome** (runs the JS charts, loads web fonts).
  Set `CHROME=/path/to/chrome` to override binary discovery.

### CI

`.github/workflows/refresh.yml` (weekly PortWatch) and `ais-sample.yml`
(4×/day AIS) share a `concurrency: group: logjam-store` so they never race for
the DuckDB file. The `data/logjam.duckdb` file is the **state store between
runs** — git-ignored for local dev, `actions/cache` in CI so history accumulates
without committing the binary.

Method and limitations for everything the tool produces: `docs/METHODOLOGY.md`.
