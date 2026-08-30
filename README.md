# bottleneck-logistics

Open-source logistics / supply-chain **bottleneck and opportunity identifier**.

It answers two questions from free, public data:

1. **Where is flow blocked?** Ships not transiting a chokepoint, port throughput
   collapsing versus that port's own seasonal norm.
2. **Where is the opportunity?** When one port in a substitution group is
   bottlenecked, which alternative in the same group is running at or above
   baseline and can absorb diverted volume?

Motivating case: a Strait of Hormuz disruption. Tanker transits through the
`chokepoint` collapse; Gulf ports inside the strait (Jebel Ali) fall below
baseline; ports positioned outside it (Salalah, Sohar) hold or rise -> the tool
surfaces the reroute.

## Status

**v1 vertical slice — IMF PortWatch only.** Pipeline is end to end:
ingest -> DuckDB -> rolling robust baseline -> bottleneck signals -> opportunity signals,
driven by a CLI and a weekly GitHub Actions refresh.

### What PortWatch can and cannot tell us

PortWatch is a **throughput** signal (vessels arriving / transiting), not a
**queue** signal. So v1 detects *disruption* (transit or throughput collapse),
not *dwell time* or *anchorage queue length*. Those need vessel-level AIS —
planned as a second ingest adapter (AISStream, free WebSocket) that writes into
the same `observation` table, so nothing downstream changes.

## Data sources

| Source | In v1 | Cost | Role |
|---|---|---|---|
| [IMF PortWatch](https://portwatch.imf.org) | yes | free, keyless | Daily port calls + trade volume for ~2,065 ports; daily transit counts for 28 chokepoints. Weekly refresh (Tue). |
| [AISStream.io](https://aisstream.io) | planned | free, free key | Live AIS → anchorage queue length, berth dwell time. |
| [Freightos Baltic Index](https://fbx.freightos.com) | planned | free | Lane-level container spot rates — a leading disruption signal. |
| [GDELT](https://www.gdeltproject.org) | planned | free | Event/news context for *why* a bottleneck appeared. |

Attribution: port and chokepoint activity data © IMF PortWatch, used under its
free public-use terms.

## Install

```bash
uv sync --extra dev            # core + test deps
uv sync --extra dev --extra dashboard   # also the Streamlit UI
```

## Use

```bash
uv run bottleneck refresh --full        # first run: backfill + compute (few min, ~1-2M rows)
uv run bottleneck refresh               # subsequent: incremental
uv run bottleneck status
uv run bottleneck bottlenecks --days 30
uv run bottleneck opportunities --days 30
uv run bottleneck ports --search "jebel ali"   # find PortWatch entity ids

uv run streamlit run src/bottleneck_logistics/dashboard/app.py   # needs --extra dashboard
```

## Layout

```
src/bottleneck_logistics/
├── config.py                     all tunables (env-overridable, prefix BNL_)
├── ingest/
│   ├── arcgis.py                 generic paged ArcGIS FeatureServer client
│   └── portwatch.py              PortWatch adapter -> tidy long frame
├── store/
│   ├── db.py                     DuckDB connection + schema
│   └── loaders.py                idempotent upsert into `observation`
├── analytics/
│   ├── baseline.py               trailing median/MAD robust z per series
│   ├── detect.py                 negative-tail z -> `signal` (bottleneck)
│   └── opportunity.py            substitution-group divergence -> `signal` (opportunity)
├── resources/substitution_groups.yaml   editable port clusters
├── pipeline.py                   refresh() = the whole chain
└── cli.py                        `bottleneck` command
scripts/refresh.py                cron entry point
.github/workflows/refresh.yml     weekly automated refresh
```

## Tuning

Everything in `config.py`. The knobs that matter:

- `baseline_window_days` (56) — trailing window for the baseline.
- `bottleneck_z_threshold` (2.0) — how far below normal counts as blocked.
- `opportunity_z_threshold` (1.5) — how "not-degraded" an alternative must be.
- `initial_backfill_days` (900) — history pulled on first run.

Substitution groups live in `resources/substitution_groups.yaml` — the starter
set covers the major trade lanes; extend it for yours.

## Roadmap

- [ ] AISStream adapter: anchorage polygons, queue counts, berth dwell.
- [ ] Freightos + GDELT adapters.
- [ ] FastAPI read layer over `signal` / `baseline`.
- [ ] Alerting (webhook / email) on new high-severity signals.
- [ ] Backtest harness against known events (2021 Suez, 2024–26 Red Sea/Hormuz).
```
