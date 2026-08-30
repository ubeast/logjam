# bottleneck-logistics

Open-source logistics / supply-chain **bottleneck and opportunity identifier**.

It answers three questions from free, public data:

1. **Where is flow blocked?** Ships not transiting a chokepoint, port throughput
   collapsing versus that port's own seasonal norm.
2. **Is a known disruption still ongoing, or has it recovered?** Current
   throughput vs the same calendar period a year ago (`bottleneck recovery`).
3. **Where is the opportunity?** When one port in a substitution group is
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
uv run bottleneck refresh --full        # first run: backfill + compute (~10 min, ~40M rows)
uv run bottleneck refresh               # subsequent: incremental
uv run bottleneck status
uv run bottleneck bottlenecks --days 30
uv run bottleneck opportunities --days 30
uv run bottleneck recovery --search "hormuz"    # is a known disruption still ongoing?
uv run bottleneck ports --search "jebel ali"    # find PortWatch entity ids

uv run streamlit run src/bottleneck_logistics/dashboard/app.py   # needs --extra dashboard
```

### `bottleneck recovery` — ongoing or recovered?

```
Recovery status: "hormuz"
 entity           metric   as of        now   yr-ago   % of normal   trend   verdict
 Strait of Hormuz n_total  2026-08-21   4     94       4%            flat    severe disruption ongoing
```

`% of normal` = current throughput (median over a trailing week) divided by the
median around the **same calendar date one year earlier**. This is what stays
meaningful when a disruption outlives the short baseline window.

**Caveat:** the year-over-year comparison answers "vs a year ago," not "vs
pre-crisis." If a disruption is more than ~1 year old, both the current and the
year-ago figure are depressed, and `recovery` will read "recovered" when it
really means "stably degraded." For events under a year old (the 2026 Hormuz
case) it is accurate.

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
│   ├── baseline.py               short trailing median/MAD z + year-over-year z
│   ├── detect.py                 short OR yoy negative-tail z -> `signal` (bottleneck)
│   ├── opportunity.py            substitution-group divergence -> `signal` (opportunity)
│   └── recovery.py               current vs same-period-last-year -> ongoing/recovered
├── resources/substitution_groups.yaml   editable port clusters
├── pipeline.py                   refresh() = the whole chain
└── cli.py                        `bottleneck` command
scripts/refresh.py                cron entry point
.github/workflows/refresh.yml     weekly automated refresh
```

## Tuning

Everything in `config.py`. The knobs that matter:

- `baseline_window_days` (56) — trailing window for the short baseline.
- `bottleneck_z_threshold` (2.0) — how far below normal counts as blocked.
- `yoy_lag_days` (365) / `yoy_halfwidth_days` (14) — the year-over-year comparison window.
- `recovery_tolerance` (0.20) — within this fraction of the year-ago level = "recovered".
- `opportunity_z_threshold` (1.5) — how "not-degraded" an alternative must be.
- `initial_backfill_days` (900) — history pulled on first run. Needs to exceed
  `yoy_lag_days` by a wide margin or the year-over-year baseline stays empty.

Substitution groups live in `resources/substitution_groups.yaml` — the starter
set covers the major trade lanes; extend it for yours.

## Roadmap

- [x] Year-over-year baseline so sustained disruptions stay visible (`recovery`).
- [ ] Trailing-days guard: exclude the most recent ~3 days from `bottlenecks` and
      treat a sudden exact-zero on a high-baseline series as missing data.
- [ ] Multi-year / pre-crisis baseline option (fixed reference period) so
      `recovery` can answer "vs pre-disruption", not just "vs a year ago".
- [ ] AISStream adapter: anchorage polygons, queue counts, berth dwell.
- [ ] Freightos + GDELT adapters.
- [ ] FastAPI read layer over `signal` / `baseline`.
- [ ] Alerting (webhook / email) on new high-severity signals.
- [ ] Backtest harness against known events (2021 Suez, 2024–26 Red Sea/Hormuz).
