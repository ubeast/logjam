# logjam

**Find the key log in global trade flow** — where cargo movement is blocked, and
where it reroutes.

Open-source logistics / supply-chain **bottleneck and opportunity identifier**.

It answers three questions from free, public data:

1. **Where is flow blocked?** Ships not transiting a chokepoint, port throughput
   collapsing versus that port's own seasonal norm.
2. **Is a known disruption still ongoing, or has it recovered?** Current
   throughput vs the same calendar period a year ago (`logjam recovery`).
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
**queue** signal. The **AISStream adapter** adds the queue signal: it samples the
live AIS stream and counts vessels sitting at anchor off a port (`vessels_at_anchor`)
and vessels moving through a chokepoint (`ais_transiting`, a same-day cross-check
on PortWatch's weekly `n_total`). Both write into the same `observation` table, so
baselines, detection, and the `recovery` command pick them up unchanged.

## Data sources

| Source | In v1 | Cost | Role |
|---|---|---|---|
| [IMF PortWatch](https://portwatch.imf.org) | yes | free, keyless | Daily port calls + trade volume for ~2,065 ports; daily transit counts for 28 chokepoints. Weekly refresh (Tue). |
| [AISStream.io](https://aisstream.io) | yes | free, free key | Live AIS, sampled: anchorage-queue counts per port, transit counts per chokepoint. Needs `LOGJAM_AISSTREAM_API_KEY`. |
| [Freightos Baltic Index](https://fbx.freightos.com) | planned | free | Lane-level container spot rates — a leading disruption signal. |
| [GDELT](https://www.gdeltproject.org) | planned | free | Event/news context for *why* a bottleneck appeared. |

Attribution: port and chokepoint activity data © IMF PortWatch, used under its
free public-use terms.

## Install

```bash
git clone https://github.com/ubeast/logjam
cd logjam
uv sync --extra dev            # core + test deps
uv sync --extra dev --extra dashboard   # also the Streamlit UI
```

## Use

```bash
uv run logjam refresh --full        # first run: backfill + compute (~10 min, ~40M rows)
uv run logjam refresh               # subsequent: incremental
uv run logjam status
uv run logjam bottlenecks --days 30
uv run logjam opportunities --days 30
uv run logjam recovery --search "hormuz"    # is a known disruption still ongoing?
uv run logjam ports --search "jebel ali"    # find PortWatch entity ids

# Live AIS (needs LOGJAM_AISSTREAM_API_KEY from aisstream.io):
uv run logjam ais-collect --minutes 30      # sample the stream to data/ais_raw/
uv run logjam ais-reduce                    # fold captures into the store
uv run logjam refresh                       # then recompute baselines + signals

uv run streamlit run src/logjam/dashboard/app.py   # needs --extra dashboard
```

### `logjam recovery` — ongoing or recovered?

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
src/logjam/
├── config.py                     all tunables (env-overridable, prefix LOGJAM_)
├── ingest/
│   ├── arcgis.py                 generic paged ArcGIS FeatureServer client
│   ├── portwatch.py              PortWatch adapter -> tidy long frame
│   ├── aisstream.py              AISStream sampler -> raw Parquet captures
│   └── ais_zones.py              geofences (port circles + chokepoint boxes)
├── store/
│   ├── db.py                     DuckDB connection + schema
│   └── loaders.py                idempotent upsert into `observation`
├── analytics/
│   ├── baseline.py               short trailing median/MAD z + year-over-year z
│   ├── detect.py                 negative-tail z (throughput) + anchor-queue spike -> `signal`
│   ├── ais_reduce.py             raw AIS Parquet -> daily per-zone metrics -> `observation`
│   ├── opportunity.py            substitution-group divergence -> `signal` (opportunity)
│   └── recovery.py               current vs same-period-last-year -> ongoing/recovered
├── resources/
│   ├── substitution_groups.yaml  editable port clusters
│   ├── ais_zones.yaml            AIS subscription regions + port watchlist
│   └── geo/                      PortWatch coordinates + the briefs' basemap
├── pipeline.py                   refresh() = the whole chain (incl. AIS reduce)
└── cli.py                        `logjam` command
scripts/refresh.py                cron entry point
scripts/reports/                  disruption-brief generators (_brief.py = shared renderer)
scripts/reports/build_geo_assets.py  rebuild resources/geo/ (run once, needs network)
scripts/build_pdfs.py             render every brief HTML + METHODOLOGY.md to PDF
reports/                          published briefs (.json / .md / .html / .pdf)
docs/METHODOLOGY.md               how baselines, detection, and recovery work
.github/workflows/refresh.yml     weekly PortWatch refresh
.github/workflows/ais-sample.yml  AIS stream sample + reduce (every few hours)
```

## Reports

`reports/` holds finished analytical briefs backed by reproducible generator
scripts in `scripts/reports/`. Each script re-derives every figure from the local
DuckDB store — nothing is hand-transcribed — and writes its data to
`reports/data/*.json`. All three briefs share one visual system and renderer
(`scripts/reports/_brief.py`); each generator emits `.json` + `.md` + `.html`,
and `scripts/build_pdfs.py` renders the `.pdf`.

- **`reports/hormuz_container_2026.html`** — container shipping through the Strait
  of Hormuz after the **2026 Iran conflict** (a separate shock from the Red Sea
  crisis): transits at ~7% of a fixed 2023 baseline since March 2026, Jebel Ali
  at ~18%, a cross-chokepoint chart showing the two crises are independent, and
  the reroute to Indian west-coast / Salalah / Egyptian Mediterranean ports — a
  map (real Natural Earth basemap, PortWatch port coordinates) of where container
  calls were lost and gained, and a capacity read showing the substitute ports
  are mostly already near their own operating ceilings.
  `uv run python scripts/reports/hormuz_container_2026.py`
- **`reports/suez_redsea_2026.html`** — the Suez Canal two and a half years into
  the Red Sea diversion: total transits back to ~55% of pre-crisis on tankers and
  bulk, container transits stuck at ~46% with no recovery trend, and the Cape of
  Good Hope carrying the diverted box trade (+230%).
  `uv run python scripts/reports/suez_redsea_2026.py`
- **`reports/horn_of_africa_2026.html`** — the Bab el-Mandeb Strait (the southern
  Red Sea gate at the Horn of Africa): containers at ~27% of pre-crisis and
  capacity at ~7%, a provisional mid-2026 dip that lines up with the Hormuz
  crisis, Djibouti holding as the regional anchor, and Saudi Red Sea ports
  (Jeddah −55%, King Abdullah −67%) as the biggest port-level casualties.
  `uv run python scripts/reports/horn_of_africa_2026.py`

All three briefs compare against a **fixed pre-crisis 2023 quarter** (the Hormuz
brief's reroute section uses the immediate pre-conflict months instead, since
some candidate ports grew organically over 2023–2025). They need the store
backfilled past the default 900-day window —
`LOGJAM_INITIAL_BACKFILL_DAYS=1400 uv run logjam refresh --full`.

Method and limitations for everything the tool produces: **[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md)**.

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
- [x] AISStream adapter: sampled anchorage-queue + chokepoint-transit counts
      (`ais-collect` / `ais-reduce`; geofences in `resources/ais_zones.yaml`).
- [ ] AIS berth-dwell time (needs per-vessel anchorage→berth state tracking).
- [ ] Multi-year / pre-crisis baseline option (fixed reference period) so
      `recovery` can answer "vs pre-disruption", not just "vs a year ago".
- [ ] Freightos + GDELT adapters.
- [ ] FastAPI read layer over `signal` / `baseline`.
- [ ] Alerting (webhook / email) on new high-severity signals.
- [ ] Backtest harness against known events (2021 Suez, 2024–26 Red Sea/Hormuz).
