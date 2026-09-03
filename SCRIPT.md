# Code With Me — building `logjam`

A linear, follow-along screencast script. It reconstructs the project from an
empty directory to a working tool in **8 segments (~65 min)**. No dead ends, no
Q&A — every step lands.

**What we build:** an open-source tool that reads free IMF PortWatch data and
flags (a) where cargo flow is blocked — a port or maritime chokepoint whose
throughput has collapsed versus its own seasonal norm — and (b) reroute
opportunities — when one port in a substitution group is bottlenecked, which
group-mate has headroom to absorb the volume. Motivating case: a Strait of
Hormuz disruption.

**Stack:** Python 3.11+, `uv`, `src/` layout, `httpx`, `pandas`, DuckDB,
`typer`, `pydantic-settings`, `pytest`.

---

## How to use this script

Each segment has:

- **Runtime / Goal / Files** — the header.
- **SAY** — narration, spoken to camera or voiceover.
- **DO** — commands to run in the terminal.
- **TYPE** — the code to write, file by file. Type it live or paste-and-explain.
- **NARRATE WHILE TYPING** — the callouts that matter for that block.
- **RUN** — the verification that closes the segment.

The code blocks are the finished project verbatim — if you get lost, the repo is
the source of truth.

| # | Segment | Runtime |
|---|---|---|
| 1 | Project scaffold | 6 min |
| 2 | Generic ArcGIS client | 7 min |
| 3 | PortWatch adapter → tidy frame | 10 min |
| 4 | The DuckDB store | 8 min |
| 5 | The baseline (rolling robust-z + year-over-year) | 12 min |
| 6 | Detection, opportunity, recovery | 12 min |
| 7 | Pipeline + CLI, run it for real | 6 min |
| 8 | Tests, CI, the report | 6 min |

---

## Segment 1 — Project scaffold

**Runtime:** 6 min
**Goal:** a GitHub-ready package skeleton with one place for every tunable.
**Files:** `pyproject.toml`, `src/logjam/__init__.py`, `config.py`, `.gitignore`

### SAY

> We're building a supply-chain bottleneck detector. It pulls free public
> shipping data, learns each port's normal rhythm, and flags the ones that have
> fallen off a cliff — plus where the diverted cargo is going instead. Let's
> start with a clean, packaging-ready Python project. I'm using `uv` for
> everything — it's fast and it manages the virtualenv for us.

### DO

```bash
mkdir logjam && cd logjam
git init
uv init --package --name logjam --python 3.11
mkdir -p src/logjam/{ingest,store,analytics,dashboard,resources}
```

### TYPE — `pyproject.toml`

```toml
[project]
name = "logjam"
version = "0.1.0"
description = "Open-source logistics / supply-chain bottleneck and opportunity identifier"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "Michael Schertz", email = "michael.schertz@gmail.com" }]
keywords = ["logistics", "supply-chain", "ports", "ais", "congestion", "osint"]

dependencies = [
    "httpx>=0.27",
    "duckdb>=1.1",
    "pandas>=2.2",
    "numpy>=1.26",
    "pyyaml>=6.0",
    "typer>=0.12",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "rich>=13.7",
]

[project.optional-dependencies]
dashboard = ["streamlit>=1.36", "pydeck>=0.9"]
api = ["fastapi>=0.111", "uvicorn>=0.30"]
dev = ["pytest>=8.2", "pytest-cov>=5.0", "ruff>=0.5", "mypy>=1.10", "respx>=0.21"]

[project.scripts]
logjam = "logjam.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/logjam"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.11"
strict = true
plugins = []

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

### NARRATE WHILE TYPING

- `httpx` for the HTTP client, `duckdb` as the analytical database,
  `pandas` for the transforms, `typer` + `rich` for the CLI.
- **Optional-dependency groups**: the core install stays lean; `dashboard`
  pulls Streamlit, `dev` pulls the test tools.
- `[project.scripts]` — installing the package gives us a `logjam` command
  on the PATH.
- `src/` layout plus `hatchling` — standard, boring, correct. Ruff and mypy
  strict from day one so we never dig out of a lint hole later.

### TYPE — `src/logjam/__init__.py`

```python
"""Open-source logistics / supply-chain bottleneck and opportunity identifier.

Pipeline overview
-----------------
1. ``ingest``    - pull raw daily activity from external sources (PortWatch first).
2. ``store``     - normalise into a DuckDB analytical database.
3. ``analytics`` - compute per-series baselines, flag bottlenecks, score opportunities.

Everything is driven from :mod:`logjam.cli` or ``scripts/refresh.py``.
"""

__version__ = "0.1.0"
```

### TYPE — `src/logjam/config.py`

```python
"""Runtime configuration.

All tunables live here so a follow-on developer has exactly one place to look.
Override any field with an environment variable prefixed ``LOGJAM_`` (e.g.
``LOGJAM_DB_PATH=/tmp/foo.duckdb``) or a ``.env`` file in the project root.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOGJAM_", env_file=".env", extra="ignore")

    # --- Storage -------------------------------------------------------------
    db_path: Path = Field(default=_PROJECT_ROOT / "data" / "logjam.duckdb")

    # --- PortWatch (IMF) ArcGIS FeatureServer endpoints --------------------
    # Public, keyless. Refreshed weekly (Tuesdays ~09:00 ET). Verified 2026-08.
    portwatch_ports_url: str = (
        "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/"
        "Daily_Ports_Data/FeatureServer/0/query"
    )
    portwatch_chokepoints_url: str = (
        "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/"
        "Daily_Chokepoints_Data/FeatureServer/0/query"
    )
    # ArcGIS servers cap a single response; we page with resultOffset. This
    # layer's maxRecordCount is 1000 but it honours maxRecordCountFactor, so
    # 5000/request is fine and cuts round-trips 5x.
    arcgis_page_size: int = 5000
    http_timeout_s: float = 60.0

    # --- Backfill window ---------------------------------------------------
    # On an empty database, how many days of history to pull. PortWatch has
    # data back to ~2019; a few years is plenty to establish seasonal baselines
    # without a multi-million-row first sync.
    initial_backfill_days: int = 900

    # --- Short baseline / detection -------------------------------------
    baseline_window_days: int = 56  # trailing window for the rolling baseline
    baseline_min_observations: int = 21  # require this many points or skip the series
    bottleneck_z_threshold: float = 2.0  # |robust z| above which a day is flagged
    # Direction that counts as a *bottleneck* per metric (a throughput collapse
    # or a chokepoint-transit collapse both mean "flow is blocked").
    # Opportunities look at the opposite tail.
    opportunity_z_threshold: float = 1.5

    # --- Year-over-year baseline ----------------------------------------
    # The short baseline catches a disruption's *onset* but is blind to one that
    # outlives its window ("the crisis becomes the new normal"). The YoY
    # baseline compares each day to the same calendar period ~1 year earlier -
    # uncontaminated as long as the disruption is under a year old - so it
    # answers "is this still abnormal, or has it recovered?".
    yoy_lag_days: int = 365
    yoy_halfwidth_days: int = 14  # +/- window around the year-ago date
    yoy_min_observations: int = 7  # need this many year-ago points or skip
    # Fraction of the year-ago level within which a series counts as "recovered".
    recovery_tolerance: float = 0.20
    # `logjam recovery` evaluates a trailing window (not a single day) and
    # skips the most recent days, which PortWatch often under-reports.
    recovery_window_days: int = 7
    recovery_trailing_exclude_days: int = 2

    @property
    def resources_dir(self) -> Path:
        return Path(__file__).resolve().parent / "resources"

    @property
    def substitution_groups_path(self) -> Path:
        return self.resources_dir / "substitution_groups.yaml"


settings = Settings()
```

### NARRATE WHILE TYPING

- Every magic number in the project lives here — window lengths, z-score
  thresholds, backfill span. A follow-on dev has one file to read.
- `pydantic-settings` means each of these is overridable by a `LOGJAM_`-prefixed
  env var or a `.env` file, with type coercion for free.
- The two ArcGIS URLs are the entire external surface of v1.
- Note the two baseline families already sketched here: a **short** 56-day
  rolling window, and a **year-over-year** comparison. Segment 5 is where that
  pays off.

### TYPE — `.gitignore`

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
*.egg-info/
.mypy_cache/
.ruff_cache/
.pytest_cache/
.coverage

# Project data / local artifacts
data/*.duckdb
data/*.duckdb.wal
data/raw/
*.parquet

# Env
.env

# macOS
.DS_Store
```

### NARRATE

> The DuckDB file gets to multiple gigabytes — it never goes in git. It's local
> state, rebuilt from the API.

### RUN

```bash
uv sync --extra dev
uv run python -c "from logjam.config import settings; print(settings.db_path)"
```

> Package imports, config resolves. Scaffold done.

---

## Segment 2 — Generic ArcGIS client

**Runtime:** 7 min
**Goal:** one reusable function that pages through any ArcGIS FeatureServer layer.
**Files:** `src/logjam/ingest/arcgis.py`

### SAY

> PortWatch publishes its data as hosted ArcGIS feature layers. ArcGIS caps how
> many rows one query returns, so anything past the first page needs offset
> paging. That's annoying plumbing that has nothing to do with shipping — so we
> isolate it in one generic function and never think about it again.

### TYPE — `src/logjam/ingest/arcgis.py`

```python
"""Minimal ArcGIS FeatureServer query client.

PortWatch publishes its data as hosted ArcGIS feature layers. A single query
response is capped by the server (``maxRecordCount``), so anything beyond the
first page must be retrieved with ``resultOffset`` paging. This module hides
that loop.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from logjam.config import settings


def query_all(
    url: str,
    *,
    where: str = "1=1",
    out_fields: str = "*",
    order_by: str = "date ASC",
    page_size: int | None = None,
    timeout_s: float | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield attribute dicts for every feature matching ``where``.

    Paging stops when the server returns fewer rows than requested and no
    ``exceededTransferLimit`` flag - the standard ArcGIS end-of-data signal.

    Raises:
        httpx.HTTPStatusError: on any non-2xx response.
        RuntimeError: if the server returns an ``error`` payload (ArcGIS returns
            HTTP 200 with an error body for bad queries).
    """
    page_size = page_size or settings.arcgis_page_size
    timeout_s = timeout_s or settings.http_timeout_s
    offset = 0

    # PortWatch's layer has maxRecordCount=1000 but advertises
    # supportsMaxRecordCountFactor, so factor * 1000 rows come back per request.
    # Keep page_size == maxRecordCount * factor so paging math stays correct.
    factor = max(1, round(page_size / 1000))

    with httpx.Client(timeout=timeout_s) as client:
        while True:
            params = {
                "where": where,
                "outFields": out_fields,
                "orderByFields": order_by,
                "resultOffset": offset,
                "resultRecordCount": page_size,
                "maxRecordCountFactor": factor,
                "returnGeometry": "false",
                "f": "json",
            }
            resp = client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()

            if "error" in payload:
                raise RuntimeError(f"ArcGIS error from {url}: {payload['error']}")

            features = payload.get("features", [])
            for feat in features:
                yield feat["attributes"]

            if len(features) < page_size and not payload.get("exceededTransferLimit"):
                return
            offset += len(features)
            if not features:  # defensive: avoid an infinite loop on odd servers
                return
```

### NARRATE WHILE TYPING

- It's a **generator** — `yield` one attribute dict per feature. Callers can
  stream millions of rows without holding them all in memory.
- `returnGeometry=false` — we want the numbers, not the map polygons. Big
  bandwidth saving.
- `maxRecordCountFactor` — the layer's stated limit is 1000 rows, but it honours
  a multiplier, so we ask for 5000 at a time and cut round-trips 5×.
- The two failure modes: a real HTTP error (`raise_for_status`) and ArcGIS's
  charming habit of returning **HTTP 200 with an error body** for a bad query —
  we check for that `"error"` key explicitly.
- Termination: a short page with no `exceededTransferLimit` flag is ArcGIS's
  "that's everything" signal. The empty-features check is belt-and-braces
  against a misbehaving server.

### RUN

```bash
uv run python -c "
from logjam.ingest.arcgis import query_all
from logjam.config import settings
rows = query_all(settings.portwatch_chokepoints_url, where=\"date >= DATE '2026-08-01'\")
print(next(rows))
"
```

> One real feature dict from PortWatch. The paging layer works. Now let's make
> sense of what's in it.

---

## Segment 3 — PortWatch adapter → tidy frame

**Runtime:** 10 min
**Goal:** turn PortWatch's two wide layers into one tidy long DataFrame with a
fixed shape.
**Files:** `src/logjam/ingest/portwatch.py`, `ingest/__init__.py`

### SAY

> PortWatch has two layers: daily port data — port calls and trade volume for
> about 2,000 ports — and daily chokepoint data — transit counts for 28 straits
> and canals like Hormuz, Suez, Panama. Each row is wide: dozens of metric
> columns. We're going to melt both into one **long** format —
> one row per entity, per date, per metric — so everything downstream sees a
> single shape no matter how many sources we add later.

### TYPE — `src/logjam/ingest/portwatch.py`

```python
"""IMF PortWatch ingestion adapter.

Source: https://portwatch.imf.org  (Data & Methodology page for definitions).
Licence: free public use with attribution to IMF PortWatch.

PortWatch publishes two daily feature layers, both derived from satellite AIS
via the UN Global Platform and refreshed weekly (Tuesdays ~09:00 ET):

* ``Daily_Ports_Data``        - port calls + estimated import/export volume,
                                for ~2,065 ports.
* ``Daily_Chokepoints_Data``  - transit counts + estimated cargo capacity
                                for 28 maritime chokepoints (Hormuz, Suez,
                                Panama, Bab-el-Mandeb, ...).

What this gives us (and what it does not)
----------------------------------------
PortWatch is a *throughput* signal, not a *queue* signal: it counts vessels
arriving/transiting, not vessels waiting at anchor or berth dwell time. So from
this source we detect:

* Port throughput anomalies  - a sharp fall in port calls / trade volume vs a
  port's own seasonal baseline (disruption, strike, weather, conflict).
* Chokepoint transit anomalies - the most direct signal for events like the
  2026 Strait of Hormuz crisis: tanker transits through ``chokepoint`` collapse.

Anchorage queue length and berth dwell time require vessel-level AIS and will
come from a separate adapter (AISStream) later.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from logjam.config import settings
from logjam.ingest.arcgis import query_all

# Columns we keep as measures. Everything else (year/month/day/ObjectId) is
# either redundant with ``date`` or ArcGIS bookkeeping.
_PORT_METRICS: tuple[str, ...] = (
    "portcalls_container",
    "portcalls_dry_bulk",
    "portcalls_general_cargo",
    "portcalls_roro",
    "portcalls_tanker",
    "portcalls_cargo",
    "portcalls",
    "import_container",
    "import_dry_bulk",
    "import_general_cargo",
    "import_roro",
    "import_tanker",
    "import_cargo",
    "import",
    "export_container",
    "export_dry_bulk",
    "export_general_cargo",
    "export_roro",
    "export_tanker",
    "export_cargo",
    "export",
)

_CHOKEPOINT_METRICS: tuple[str, ...] = (
    "n_container",
    "n_dry_bulk",
    "n_general_cargo",
    "n_roro",
    "n_tanker",
    "n_cargo",
    "n_total",
    "capacity_container",
    "capacity_dry_bulk",
    "capacity_general_cargo",
    "capacity_roro",
    "capacity_tanker",
    "capacity_cargo",
    "capacity_total",
)

TIDY_COLUMNS: list[str] = [
    "entity_type",
    "entity_id",
    "entity_name",
    "country",
    "iso3",
    "date",
    "metric",
    "value",
]


def _parse_arcgis_date(value: Any) -> dt.date | None:
    """Parse an ArcGIS ``esriFieldTypeDateOnly`` value.

    This layer returns an ISO string (``"2026-08-21"``). Other ArcGIS services
    return epoch milliseconds for the same field type, so we handle both.
    """
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return dt.date.fromisoformat(value[:10])
    # numeric: epoch milliseconds (UTC)
    return dt.datetime.fromtimestamp(value / 1000, tz=dt.UTC).date()


def _where_range(since: dt.date | None, until: dt.date | None) -> str:
    """Build an ArcGIS where-clause for a half-open date range [since, until)."""
    parts: list[str] = []
    if since is not None:
        parts.append(f"date >= DATE '{since.isoformat()}'")
    if until is not None:
        parts.append(f"date < DATE '{until.isoformat()}'")
    return " AND ".join(parts) if parts else "1=1"


def _to_tidy(
    rows: list[dict[str, Any]],
    *,
    entity_type: str,
    metrics: tuple[str, ...],
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=TIDY_COLUMNS)

    wide = pd.DataFrame(rows)
    wide["date"] = wide["date"].map(_parse_arcgis_date)
    wide = wide.dropna(subset=["date"])

    id_vars = {
        "entity_id": "portid",
        "entity_name": "portname",
        "country": "country",
        "iso3": "ISO3",
    }
    # Chokepoint layer has no country/ISO3 columns.
    present_id_vars = {k: v for k, v in id_vars.items() if v in wide.columns}
    keep = list(present_id_vars.values()) + ["date"]
    present_metrics = [m for m in metrics if m in wide.columns]

    long = wide[keep + present_metrics].melt(
        id_vars=keep,
        value_vars=present_metrics,
        var_name="metric",
        value_name="value",
    )
    long = long.rename(columns={v: k for k, v in present_id_vars.items()})
    for missing in ("country", "iso3"):
        if missing not in long.columns:
            long[missing] = None

    long["entity_type"] = entity_type
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long = long.dropna(subset=["value"])
    return long[TIDY_COLUMNS].reset_index(drop=True)


def fetch_portwatch(
    since: dt.date | None = None,
    until: dt.date | None = None,
) -> pd.DataFrame:
    """Return tidy PortWatch observations for ports **and** chokepoints.

    Args:
        since: only pull rows on/after this date.
        until: only pull rows strictly before this date. Together they form a
            half-open range so month-by-month backfill chunks do not overlap.
            ``since=None`` pulls the server's full history - a few million rows
            per year, so the pipeline chunks large backfills (see
            :func:`logjam.pipeline.refresh`).

    Returns:
        DataFrame with :data:`TIDY_COLUMNS`. ``entity_type`` is ``"port"`` or
        ``"chokepoint"``.
    """
    where = _where_range(since, until)
    port_rows = list(query_all(settings.portwatch_ports_url, where=where))
    choke_rows = list(query_all(settings.portwatch_chokepoints_url, where=where))

    ports = _to_tidy(port_rows, entity_type="port", metrics=_PORT_METRICS)
    chokes = _to_tidy(choke_rows, entity_type="chokepoint", metrics=_CHOKEPOINT_METRICS)
    return pd.concat([ports, chokes], ignore_index=True)


def month_starts(since: dt.date, until: dt.date) -> list[dt.date]:
    """First-of-month boundaries spanning [since, until], for chunked backfill."""
    cur = since.replace(day=1)
    out: list[dt.date] = []
    while cur <= until:
        out.append(cur)
        cur = (cur.replace(day=28) + dt.timedelta(days=7)).replace(day=1)
    return out


def default_since(latest_stored: dt.date | None) -> dt.date:
    """Pick a ``since`` date: incremental if we have data, else a bounded backfill.

    We re-pull a small overlap (``baseline_window_days`` is overkill; 10 days is
    enough) because PortWatch revises recent estimates as more AIS arrives.
    """
    if latest_stored is not None:
        return latest_stored - dt.timedelta(days=10)
    return dt.date.today() - dt.timedelta(days=settings.initial_backfill_days)
```

### NARRATE WHILE TYPING

- `TIDY_COLUMNS` is the **contract**. Every ingest adapter — PortWatch now,
  AISStream or Freightos later — returns exactly this 8-column shape. Nothing
  downstream changes when we add a source.
- The metric tuples are an allow-list. PortWatch rows carry `year`, `month`,
  `ObjectId` junk we don't want; we melt only the columns we name.
- `_parse_arcgis_date` handles both formats ArcGIS uses for a date-only field —
  ISO string here, epoch milliseconds on other services. Cheap insurance.
- `_where_range` builds a **half-open** interval `[since, until)`. That's what
  lets us backfill month-by-month with zero overlap.
- `_to_tidy` is the melt. The chokepoint layer has no `country`/`ISO3` columns,
  so we detect which id columns are present and backfill the missing ones with
  `None` — same output shape for both layers.
- `pd.to_numeric(..., errors="coerce")` then `dropna` — a non-numeric or missing
  measurement becomes NaN and drops out rather than poisoning the store.
- `default_since` — incremental refresh re-pulls a 10-day overlap because
  PortWatch **revises** its recent estimates as more satellite AIS lands. The
  store's upsert (next segment) makes that safe.

### TYPE — `src/logjam/ingest/__init__.py`

```python
"""Ingestion adapters.

Each adapter is responsible for one external source and exposes a single
``fetch_*`` function that returns a tidy :class:`pandas.DataFrame` in the
long format the store expects:

    entity_type | entity_id | entity_name | country | iso3 | date | metric | value

Adding a new source (AISStream, Freightos, GDELT, ...) means adding a module
here that produces that same shape - nothing downstream needs to change.
"""

from logjam.ingest.portwatch import fetch_portwatch

__all__ = ["fetch_portwatch"]
```

### RUN

```bash
uv run python -c "
import datetime as dt
from logjam.ingest.portwatch import fetch_portwatch
df = fetch_portwatch(since=dt.date(2026, 8, 1), until=dt.date(2026, 8, 8))
print(df.shape)
print(df[df.entity_name.str.contains('Hormuz', case=False, na=False)].head())
"
```

> One long frame, both entity types, Hormuz transits in there. Time to store it.

---

## Segment 4 — The DuckDB store

**Runtime:** 8 min
**Goal:** an embedded analytical database with an idempotent upsert.
**Files:** `src/logjam/store/db.py`, `store/loaders.py`, `store/__init__.py`

### SAY

> The workload is read-heavy analytical aggregation over a few million rows,
> single writer, no server. That's exactly DuckDB's sweet spot — one file, zero
> setup. We define three tables: `observation` for the raw tidy data,
> `baseline` for the per-series norms we'll compute, and `signal` for the
> bottlenecks and opportunities we detect.

### TYPE — `src/logjam/store/db.py`

```python
"""Connection handling and schema definition."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import duckdb

from logjam.config import settings

# Bump when the schema changes in a non-additive way; ``init_schema`` is
# additive-only today, so this is informational.
SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS observation (
    entity_type   TEXT    NOT NULL,   -- 'port' | 'chokepoint'
    entity_id     TEXT    NOT NULL,   -- PortWatch portid, e.g. 'port1114'
    entity_name   TEXT,
    country       TEXT,
    iso3          TEXT,
    obs_date      DATE    NOT NULL,
    metric        TEXT    NOT NULL,   -- e.g. 'portcalls_container', 'n_tanker'
    value         DOUBLE  NOT NULL,
    source        TEXT    NOT NULL DEFAULT 'portwatch',
    ingested_at   TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (entity_type, entity_id, obs_date, metric, source)
);

CREATE INDEX IF NOT EXISTS observation_date_idx ON observation (obs_date);
CREATE INDEX IF NOT EXISTS observation_entity_idx ON observation (entity_type, entity_id, metric);

-- Per-series baseline, recomputed by analytics.baseline. Carries two
-- baselines: a short trailing window (onset detection) and a year-over-year
-- comparison (sustained-regime / recovery detection). YoY columns are NULL
-- until a series has ~1 year of prior history.
CREATE TABLE IF NOT EXISTS baseline (
    entity_type   TEXT   NOT NULL,
    entity_id     TEXT   NOT NULL,
    metric        TEXT   NOT NULL,
    obs_date      DATE   NOT NULL,
    value         DOUBLE NOT NULL,     -- the actual observed value that day
    expected      DOUBLE NOT NULL,     -- short trailing median
    scale         DOUBLE NOT NULL,     -- short trailing MAD (scaled to ~sigma)
    robust_z      DOUBLE NOT NULL,     -- (value - expected) / scale
    n_obs         INTEGER NOT NULL,
    expected_yoy  DOUBLE,              -- median around the same date ~1yr earlier
    robust_z_yoy  DOUBLE,              -- (value - expected_yoy) / scale
    pct_of_yoy    DOUBLE,              -- value / expected_yoy
    n_obs_yoy     INTEGER,
    computed_at   TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (entity_type, entity_id, metric, obs_date)
);

-- Detected bottlenecks (flow blocked) and opportunities (flow available).
CREATE TABLE IF NOT EXISTS signal (
    signal_type   TEXT   NOT NULL,     -- 'bottleneck' | 'opportunity'
    entity_type   TEXT   NOT NULL,
    entity_id     TEXT   NOT NULL,
    entity_name   TEXT,
    metric        TEXT   NOT NULL,
    obs_date      DATE   NOT NULL,
    value         DOUBLE NOT NULL,
    expected      DOUBLE NOT NULL,
    robust_z      DOUBLE NOT NULL,
    severity      DOUBLE NOT NULL,     -- abs(robust_z), for ranking
    detail        JSON,                -- signal-specific context
    computed_at   TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (signal_type, entity_type, entity_id, metric, obs_date)
);
"""


def connect(db_path: Path | None = None, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


# Additive migrations for databases created by an earlier schema version.
# DuckDB's ADD COLUMN IF NOT EXISTS makes these safe to run every startup.
_MIGRATIONS_SQL = """
ALTER TABLE baseline ADD COLUMN IF NOT EXISTS expected_yoy DOUBLE;
ALTER TABLE baseline ADD COLUMN IF NOT EXISTS robust_z_yoy DOUBLE;
ALTER TABLE baseline ADD COLUMN IF NOT EXISTS pct_of_yoy DOUBLE;
ALTER TABLE baseline ADD COLUMN IF NOT EXISTS n_obs_yoy INTEGER;
"""


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(_SCHEMA_SQL)
    con.execute(_MIGRATIONS_SQL)


def latest_observation_date(
    con: duckdb.DuckDBPyConnection, *, source: str = "portwatch"
) -> dt.date | None:
    row = con.execute(
        "SELECT max(obs_date) FROM observation WHERE source = ?", [source]
    ).fetchone()
    return row[0] if row and row[0] is not None else None
```

### NARRATE WHILE TYPING

- The `observation` primary key — `(entity_type, entity_id, obs_date, metric,
  source)` — is the natural key of a measurement. That's what makes re-ingesting
  an overlapping window safe: same key, we replace.
- `baseline` carries **both** baseline families side by side. The `_yoy` columns
  are nullable — a series doesn't get a year-over-year number until it has a
  year of prior history.
- `signal` has a free-form `detail` JSON column — each signal type stashes its
  own context there without a schema change.
- `_MIGRATIONS_SQL` — `ADD COLUMN IF NOT EXISTS` on every startup. An existing
  database from an earlier version upgrades in place, no re-ingest.
- `latest_observation_date` is what drives incremental refresh.

### TYPE — `src/logjam/store/loaders.py`

```python
"""Idempotent loaders: take a tidy DataFrame, upsert into ``observation``."""

from __future__ import annotations

import duckdb
import pandas as pd

from logjam.ingest.portwatch import TIDY_COLUMNS

_REQUIRED = set(TIDY_COLUMNS)


def upsert_observations(
    con: duckdb.DuckDBPyConnection,
    tidy: pd.DataFrame,
    *,
    source: str = "portwatch",
) -> int:
    """Insert or replace observation rows. Returns the number of rows written.

    PortWatch revises recent estimates, so re-ingesting an overlapping window
    must overwrite, not duplicate - hence DELETE-then-INSERT on the natural key
    rather than a plain append.
    """
    missing = _REQUIRED - set(tidy.columns)
    if missing:
        raise ValueError(f"tidy frame missing columns: {sorted(missing)}")
    if tidy.empty:
        return 0

    staged = tidy[TIDY_COLUMNS].copy()
    staged["source"] = source
    staged = staged.rename(columns={"date": "obs_date"})

    con.register("staged_obs", staged)
    try:
        con.execute("BEGIN TRANSACTION")
        con.execute(
            """
            DELETE FROM observation o
            USING staged_obs s
            WHERE o.entity_type = s.entity_type
              AND o.entity_id   = s.entity_id
              AND o.obs_date    = s.obs_date
              AND o.metric      = s.metric
              AND o.source      = s.source
            """
        )
        con.execute(
            """
            INSERT INTO observation
                (entity_type, entity_id, entity_name, country, iso3,
                 obs_date, metric, value, source)
            SELECT entity_type, entity_id, entity_name, country, iso3,
                   obs_date, metric, value, source
            FROM staged_obs
            """
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("staged_obs")

    return len(staged)
```

### NARRATE WHILE TYPING

- `con.register` hands pandas straight to DuckDB as a virtual table — no CSV, no
  temp file, zero-copy.
- **DELETE-then-INSERT** inside a transaction, keyed on the natural key. Run the
  same week twice and you get the second week's numbers, not doubles. That's the
  whole reason incremental refresh can re-pull an overlap.
- The column check up front turns a bad caller into a clear `ValueError` instead
  of a confusing SQL error.

### TYPE — `src/logjam/store/__init__.py`

```python
"""DuckDB analytical store.

One embedded file (``data/logjam.duckdb`` by default). DuckDB is a good fit
here: the workload is read-heavy analytical aggregation over a few million rows,
there is no concurrent-writer requirement, and it needs zero server setup.
Swap to Postgres/Timescale only if/when live AIS ingestion makes this
write-hot.
"""

from logjam.store.db import connect, init_schema, latest_observation_date
from logjam.store.loaders import upsert_observations

__all__ = [
    "connect",
    "init_schema",
    "latest_observation_date",
    "upsert_observations",
]
```

### RUN

```bash
uv run python -c "
import datetime as dt
from logjam.ingest.portwatch import fetch_portwatch
from logjam.store import connect, init_schema, upsert_observations
con = connect()
init_schema(con)
df = fetch_portwatch(since=dt.date(2026, 8, 1), until=dt.date(2026, 8, 15))
print('written:', upsert_observations(con, df))
print('rows now:', con.execute('SELECT count(*) FROM observation').fetchone()[0])
print('written again:', upsert_observations(con, df))
print('rows still:', con.execute('SELECT count(*) FROM observation').fetchone()[0])
"
```

> Same data twice, row count unchanged. Idempotent. Now the interesting part —
> what does "normal" mean for a port?

---

## Segment 5 — The baseline (rolling robust-z + year-over-year)

**Runtime:** 12 min
**Goal:** for every `(entity, metric)` series, a robust rolling norm and a
year-ago norm, each expressed as a z-score.
**Files:** `src/logjam/analytics/baseline.py`

### SAY

> Port-call counts are spiky — a storm, a holiday, a data revision. If we used a
> rolling **mean and standard deviation**, one weird day inflates the band for
> weeks and we go blind. So we use the robust pair: the **median** and the
> **median absolute deviation**. And we compute two baselines. The short one — a
> 56-day trailing window — catches a disruption the day it starts. But once a
> disruption outlives that window, the trailing median drifts down to the new
> low and the short baseline says "all normal here." So we add a
> **year-over-year** baseline: compare each day to the same calendar week a year
> earlier. That stays honest until the disruption itself is over a year old.

### TYPE — `src/logjam/analytics/baseline.py`

```python
"""Rolling robust baseline for every (entity, metric) series."""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from logjam.config import settings

# MAD -> sigma consistency constant for a normal distribution.
_MAD_TO_SIGMA = 1.4826


def robust_z_series(series: pd.DataFrame, window: int, min_obs: int) -> pd.DataFrame:
    """Single-series reference implementation of the baseline (used in tests).

    ``compute_baselines`` runs the same maths as vectorised groupby-rolling for
    speed; this function is the readable definition of what it computes.

    ``series`` is one sorted (entity, metric) group with columns date/value.

    Window is a *row count*, not a calendar window. PortWatch is daily and
    dense, so rows ~= days; gaps make the window look slightly further back,
    which is acceptable for a baseline. ``min_obs`` guards new/sparse series.

    ``closed="left"`` -> the current day is NOT in its own baseline, so a
    genuine anomaly cannot mask itself.

    Scale is a fast MAD approximation: the trailing median of absolute
    deviations from the trailing median. Both passes are vectorised C
    (``rolling().median()``); a strict per-window MAD via ``rolling().apply``
    is ~100x slower over tens of thousands of series and gives materially the
    same anomaly band.
    """
    v = series["value"]
    roll = v.rolling(window=window, min_periods=min_obs, closed="left")
    expected = roll.median()

    abs_dev = (v - expected).abs()
    mad_approx = abs_dev.rolling(window=window, min_periods=min_obs, closed="left").median()
    scale = (mad_approx * _MAD_TO_SIGMA).replace(0.0, np.nan)

    out = series.copy()
    out["expected"] = expected
    out["scale"] = scale
    out["robust_z"] = (v - expected) / scale
    out["n_obs"] = roll.count()
    return out.dropna(subset=["expected", "robust_z"])


def compute_baselines(con: duckdb.DuckDBPyConnection) -> int:
    """Recompute the ``baseline`` table from scratch. Returns rows written.

    Performance: this pulls the whole ``observation`` table into pandas. At a
    few million rows that is a couple of seconds and a few hundred MB. If the
    table grows past ~50M rows (e.g. after adding vessel-level AIS), push this
    into DuckDB window functions or process per entity_type in chunks.
    """
    obs = con.execute(
        """
        SELECT entity_type, entity_id, metric, obs_date AS date, value
        FROM observation
        ORDER BY entity_type, entity_id, metric, obs_date
        """
    ).df()
    if obs.empty:
        con.execute("DELETE FROM baseline")
        return 0

    window = settings.baseline_window_days
    min_obs = settings.baseline_min_observations
    keys = ["entity_type", "entity_id", "metric"]

    # Two vectorised groupby-rolling passes (see _robust_z_frame for the method).
    # `obs` is already sorted by (keys, obs_date) from the SQL query.
    def _grouped_roll(s: pd.Series) -> pd.Series:
        rolled = (
            s.groupby([obs[k] for k in keys], sort=False)
            .rolling(window=window, min_periods=min_obs, closed="left")
            .median()
        )
        # drop the group-key index levels, keep alignment to the original rows
        return rolled.reset_index(level=list(range(len(keys))), drop=True).sort_index()

    v = obs["value"]
    expected = _grouped_roll(v)
    abs_dev = (v - expected).abs()
    scale = (_grouped_roll(abs_dev) * _MAD_TO_SIGMA).replace(0.0, np.nan)
    n_obs = (
        v.groupby([obs[k] for k in keys], sort=False)
        .rolling(window=window, min_periods=min_obs, closed="left")
        .count()
        .reset_index(level=list(range(len(keys))), drop=True)
        .sort_index()
    )

    result = obs.assign(
        obs_date=obs["date"],
        expected=expected,
        scale=scale,
        robust_z=(v - expected) / scale,
        n_obs=n_obs,
    ).dropna(subset=["expected", "robust_z"])
    result = result[
        ["entity_type", "entity_id", "metric", "obs_date",
         "value", "expected", "scale", "robust_z", "n_obs"]
    ]
    result["n_obs"] = result["n_obs"].astype("int64")

    con.register("staged_baseline", result)
    try:
        con.execute("BEGIN TRANSACTION")
        con.execute("DELETE FROM baseline")
        con.execute(
            """
            INSERT INTO baseline
                (entity_type, entity_id, metric, obs_date,
                 value, expected, scale, robust_z, n_obs)
            SELECT entity_type, entity_id, metric, obs_date,
                   value, expected, scale, robust_z, n_obs
            FROM staged_baseline
            """
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("staged_baseline")

    _fill_yoy_baseline(con)
    return len(result)


def _fill_yoy_baseline(con: duckdb.DuckDBPyConnection) -> None:
    """Fill the year-over-year columns on ``baseline`` in a single SQL pass.

    For each baseline row, ``expected_yoy`` is the median observed value in a
    +/- ``yoy_halfwidth_days`` window centred ``yoy_lag_days`` before that row's
    date. Rows with fewer than ``yoy_min_observations`` year-ago points keep
    NULL YoY columns.

    Performance: this is a range self-join of ``observation`` (millions of rows)
    against ``baseline``. On a weekly refresh that is a few seconds to low tens
    of seconds; it is the heaviest single statement in the pipeline.
    """
    lag = settings.yoy_lag_days
    hw = settings.yoy_halfwidth_days
    min_obs = settings.yoy_min_observations

    con.execute(
        """
        UPDATE baseline b
        SET expected_yoy = sub.med,
            n_obs_yoy    = sub.n,
            robust_z_yoy = CASE WHEN b.scale > 0
                                THEN (b.value - sub.med) / b.scale END,
            pct_of_yoy   = CASE WHEN sub.med > 0
                                THEN b.value / sub.med END
        FROM (
            SELECT b2.entity_type, b2.entity_id, b2.metric, b2.obs_date,
                   median(o.value) AS med, count(*) AS n
            FROM baseline b2
            JOIN observation o
              ON o.entity_type = b2.entity_type
             AND o.entity_id   = b2.entity_id
             AND o.metric      = b2.metric
             AND o.obs_date BETWEEN b2.obs_date - ? AND b2.obs_date - ?
            GROUP BY 1, 2, 3, 4
            HAVING count(*) >= ?
        ) sub
        WHERE b.entity_type = sub.entity_type
          AND b.entity_id   = sub.entity_id
          AND b.metric      = sub.metric
          AND b.obs_date    = sub.obs_date
        """,
        [lag + hw, lag - hw, min_obs],
    )
```

### NARRATE WHILE TYPING

- **`robust_z_series` first** — this is the readable definition. One series in,
  the same series out with `expected` (trailing median), `scale` (trailing MAD
  × 1.4826, which puts it on the same footing as a standard deviation), and
  `robust_z = (value − expected) / scale`.
- `closed="left"` is the subtle one: **the current day is excluded from its own
  baseline**. Otherwise a huge anomaly pulls its own median toward itself and
  partly hides.
- `scale.replace(0.0, np.nan)` — a dead-flat series has MAD 0; dividing by it
  would give infinities, so those series just produce no z-score.
- **`compute_baselines`** does the identical maths but vectorised: one
  `groupby(...).rolling(...).median()` across every series at once. The comment
  is explicit about the tradeoff — a strict per-window MAD via `.apply()` is
  ~100× slower over tens of thousands of series and moves the band by
  essentially nothing.
- Performance note in the docstring is deliberate: this pulls the whole
  `observation` table into pandas. Fine at a few million rows; if AIS ingestion
  ever pushes it past ~50M, this moves into DuckDB window functions.
- **`_fill_yoy_baseline`** is one SQL statement — a range self-join. For each
  baseline row, look back ~365 days ± 14 and take the median of what actually
  happened then. `pct_of_yoy` — today as a fraction of a year ago — is the
  number the `recovery` command is built on. It's the heaviest statement in the
  pipeline; the docstring says so.

### RUN

```bash
uv run python -c "
from logjam.store import connect
from logjam.analytics.baseline import compute_baselines
con = connect()
print('baseline rows:', compute_baselines(con))
print(con.execute('''
  SELECT entity_id, obs_date, value, round(expected,1) exp, round(robust_z,2) z
  FROM baseline WHERE metric='n_total' ORDER BY obs_date DESC LIMIT 5
''').df())
"
```

> Every series now has a norm and a deviation from it. Detection is almost
> mechanical from here.

---

## Segment 6 — Detection, opportunity, recovery

**Runtime:** 12 min
**Goal:** three analytics that read `baseline` and write `signal` (or a report row).
**Files:** `analytics/detect.py`, `analytics/opportunity.py`, `analytics/recovery.py`,
`resources/substitution_groups.yaml`, `analytics/__init__.py`

### SAY

> Three questions, three modules. One: where is flow blocked right now?
> Two: given a blockage, where's the headroom to reroute? Three: for a
> disruption we already know about — is it still going, or has it recovered?

### TYPE — `src/logjam/analytics/detect.py`

```python
"""Bottleneck detection: flag days where flow collapsed vs a series' baseline."""

from __future__ import annotations

import json

import duckdb

from logjam.config import settings

# Every PortWatch metric is "more == more flow" (port calls, transits, trade
# volume, cargo capacity). A bottleneck is therefore always the *negative* tail.
# A positive spike is a surge - interesting, but tracked separately later.
_BOTTLENECK_METRICS_LIKE = (
    "portcalls%",
    "import%",
    "export%",
    "n\\_%",  # chokepoint transit counts (escaped _ for LIKE)
    "capacity%",
)


def detect_bottlenecks(con: duckdb.DuckDBPyConnection) -> int:
    """Populate ``signal`` rows of type 'bottleneck'. Returns rows written.

    A day is flagged when the **short** baseline z-score OR the **year-over-year**
    z-score is at or below ``-bottleneck_z_threshold``:

    * short trigger  -> a fresh disruption (onset).
    * yoy trigger    -> still materially below where this series was a year ago,
                        even if the short baseline has "healed" around the new
                        low level. This is what keeps a months-long event (e.g. a
                        Strait of Hormuz shutdown) visible instead of it fading
                        once the crisis becomes the trailing norm.

    ``robust_z`` / ``expected`` on the signal row reflect whichever baseline
    triggered more strongly; ``detail.trigger`` records which fired.
    """
    z = settings.bottleneck_z_threshold
    min_obs = settings.baseline_min_observations
    yoy_min = settings.yoy_min_observations
    like_clause = " OR ".join("b.metric LIKE ? ESCAPE '\\'" for _ in _BOTTLENECK_METRICS_LIKE)

    rows = con.execute(
        f"""
        SELECT b.entity_type, b.entity_id, o.entity_name, b.metric, b.obs_date,
               b.value, b.expected, b.robust_z, b.n_obs,
               b.expected_yoy, b.robust_z_yoy, b.pct_of_yoy, b.n_obs_yoy
        FROM baseline b
        JOIN (
            SELECT entity_type, entity_id, any_value(entity_name) AS entity_name
            FROM observation GROUP BY entity_type, entity_id
        ) o USING (entity_type, entity_id)
        WHERE ({like_clause})
          AND (
                (b.robust_z <= ? AND b.n_obs >= ?)
             OR (b.robust_z_yoy <= ? AND b.n_obs_yoy >= ?)
          )
        """,
        [*_BOTTLENECK_METRICS_LIKE, -abs(z), min_obs, -abs(z), yoy_min],
    ).fetchall()

    con.execute("DELETE FROM signal WHERE signal_type = 'bottleneck'")
    if not rows:
        return 0

    payload = []
    for (
        etype, eid, ename, metric, obs_date,
        value, expected, rz, n_obs,
        expected_yoy, rz_yoy, pct_yoy, n_obs_yoy,
    ) in rows:
        short_hit = rz is not None and n_obs is not None and rz <= -abs(z) and n_obs >= min_obs
        yoy_hit = (
            rz_yoy is not None and n_obs_yoy is not None
            and rz_yoy <= -abs(z) and n_obs_yoy >= yoy_min
        )
        trigger = "both" if short_hit and yoy_hit else ("short" if short_hit else "yoy")

        # Report on whichever baseline is the more extreme.
        yoy_more_extreme = rz_yoy is not None and rz is not None and rz_yoy < rz
        use_yoy = yoy_hit and (not short_hit or yoy_more_extreme)
        report_z = rz_yoy if use_yoy else rz
        report_exp = expected_yoy if use_yoy else expected
        drop_pct = (
            None if not report_exp else round(100 * (value - report_exp) / report_exp, 1)
        )
        detail = json.dumps(
            {
                "trigger": trigger,
                "drop_pct_vs_expected": drop_pct,
                "short": {
                    "expected": round(expected, 2) if expected is not None else None,
                    "robust_z": round(rz, 2) if rz is not None else None,
                    "n_obs": int(n_obs) if n_obs is not None else None,
                    "window_days": settings.baseline_window_days,
                },
                "yoy": {
                    "expected": round(expected_yoy, 2) if expected_yoy is not None else None,
                    "robust_z": round(rz_yoy, 2) if rz_yoy is not None else None,
                    "pct_of_year_ago": round(pct_yoy, 3) if pct_yoy is not None else None,
                    "n_obs": int(n_obs_yoy) if n_obs_yoy is not None else None,
                },
            }
        )
        payload.append(
            (etype, eid, ename, metric, obs_date, value, report_exp,
             report_z, abs(report_z), detail)
        )

    con.executemany(
        """
        INSERT INTO signal
            (signal_type, entity_type, entity_id, entity_name, metric, obs_date,
             value, expected, robust_z, severity, detail)
        VALUES ('bottleneck', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    return len(payload)
```

### NARRATE WHILE TYPING

- Every PortWatch metric is "bigger = more flow," so a bottleneck is **always
  the negative tail**. The `LIKE` allow-list keeps us on throughput/transit
  metrics.
- The trigger is an **OR**: short z ≤ −2 (fresh onset) *or* year-over-year z ≤
  −2 (still far below a year ago even if the short window has healed around the
  new low). `detail.trigger` records which fired — `short`, `yoy`, or `both`.
- When both fire, we report the **more extreme** one, so the number a human
  sees is the scariest true number.
- The whole `detail` blob goes in as JSON — no schema change to carry
  per-signal context.

### TYPE — `src/logjam/resources/substitution_groups.yaml`

```yaml
# Substitution groups: sets of ports that can realistically absorb each other's
# volume for a given trade lane. The opportunity detector looks for a group
# where one member is bottlenecked while another is at/above its own baseline.
#
# Each member is resolved to a PortWatch entity by (in priority order):
#   1. `portid:` if given (exact, e.g. "port1114")
#   2. `match:`  a case-insensitive SQL LIKE pattern against the port name
#               plus optional `iso3:` to disambiguate same-named ports
#
# Use `logjam ports --search "long beach"` to find portids / exact names.
# This file is a starting point - extend it for the lanes you care about.

default_metric: portcalls_container

groups:
  - name: US West Coast (Trans-Pacific gateway)
    notes: >
      LA/Long Beach dominate; Oakland, PNW and Canadian gateways are the
      classic overflow valves when San Pedro Bay backs up.
    members:
      - { match: "los angeles%", iso3: USA }
      - { match: "long beach%", iso3: USA }
      - { match: "oakland%", iso3: USA }
      - { match: "seattle%", iso3: USA }
      - { match: "tacoma%", iso3: USA }
      - { match: "prince rupert%", iso3: CAN }
      - { match: "vancouver%", iso3: CAN }

  - name: US East / Gulf Coast
    members:
      - { match: "new york%", iso3: USA }
      - { match: "savannah%", iso3: USA }
      - { match: "charleston%", iso3: USA }
      - { match: "norfolk%", iso3: USA }
      - { match: "houston%", iso3: USA }
      - { match: "%jacksonville%", iso3: USA }

  - name: North Europe (Hamburg - Le Havre range)
    members:
      - { match: "rotterdam%", iso3: NLD }
      - { match: "antwerp%", iso3: BEL }
      - { match: "hamburg%", iso3: DEU }
      - { match: "bremerhaven%", iso3: DEU }
      - { match: "le havre%", iso3: FRA }
      - { match: "zeebrugge%", iso3: BEL }

  - name: East Asia main gateways
    members:
      - { match: "shanghai%", iso3: CHN }
      - { match: "ningbo%", iso3: CHN }
      - { match: "shenzhen%", iso3: CHN }
      - { match: "qingdao%", iso3: CHN }
      - { match: "busan%", iso3: KOR }

  - name: Arabian Peninsula (Strait of Hormuz exposure)
    notes: >
      Jebel Ali and other Gulf ports sit inside Hormuz. Salalah, Sohar and
      Fujairah offer varying degrees of "outside the strait" positioning -
      the key opportunity signal during a Hormuz disruption.
    members:
      - { match: "jebel ali%", iso3: ARE }
      - { match: "fujairah%", iso3: ARE }
      - { match: "sohar%", iso3: OMN }
      - { match: "salalah%", iso3: OMN }
      - { match: "dammam%", iso3: SAU }
      - { match: "jeddah%", iso3: SAU }

  - name: Suez vs Cape reroute (chokepoints)
    entity_type: chokepoint
    default_metric: n_total
    notes: >
      Not interchangeable ports but interchangeable *routes*. When Suez /
      Bab-el-Mandeb transits collapse, Cape of Good Hope transits rise - the
      detector surfaces that as an opportunity to pre-book Cape capacity.
    members:
      - { match: "suez%" }
      - { match: "bab-el-mandeb%" }
      - { match: "%good hope%" }
      - { match: "%gibraltar%" }
```

### NARRATE

> This is the one piece of domain knowledge we hand-author: which ports actually
> compete for the same cargo. Each member is either an exact PortWatch id or a
> name pattern with an optional country code. The last group is routes, not
> ports — when Suez collapses, Cape of Good Hope traffic rises.

### TYPE — `src/logjam/analytics/opportunity.py`

```python
"""Opportunity detection: bottleneck in one group member, headroom in another.

Reads ``resources/substitution_groups.yaml``, resolves each member to a
PortWatch entity, and for every date where at least one member is bottlenecked
emits an 'opportunity' signal for each member that is simultaneously running
at or above its own baseline (robust_z >= -opportunity_z_threshold, i.e. not
itself degraded; a positive z means it is actively absorbing diverted volume).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import yaml

from logjam.config import settings


@dataclass(frozen=True)
class ResolvedMember:
    group: str
    entity_type: str
    entity_id: str
    entity_name: str
    metric: str


def _load_groups(path: Path) -> tuple[list[dict[str, Any]], str]:
    with path.open() as fh:
        doc = yaml.safe_load(fh)
    return doc.get("groups", []), doc.get("default_metric", "portcalls_container")


def _resolve_member(
    con: duckdb.DuckDBPyConnection,
    member: dict[str, Any],
    entity_type: str,
) -> tuple[str, str] | None:
    """Return (entity_id, entity_name) or None if unresolved/ambiguous-empty."""
    if "portid" in member:
        row = con.execute(
            "SELECT entity_id, any_value(entity_name) FROM observation "
            "WHERE entity_id = ? GROUP BY entity_id",
            [member["portid"]],
        ).fetchone()
        return (row[0], row[1]) if row else None

    where = ["entity_type = ?", "lower(entity_name) LIKE lower(?)"]
    params: list[Any] = [entity_type, member["match"]]
    if member.get("iso3"):
        where.append("iso3 = ?")
        params.append(member["iso3"])

    # Prefer the highest-volume match (most rows) when a pattern hits several.
    row = con.execute(
        f"""
        SELECT entity_id, any_value(entity_name) AS name, count(*) AS n
        FROM observation
        WHERE {' AND '.join(where)}
        GROUP BY entity_id
        ORDER BY n DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    return (row[0], row[1]) if row else None


def resolve_groups(con: duckdb.DuckDBPyConnection) -> tuple[list[ResolvedMember], list[str]]:
    groups, top_default_metric = _load_groups(settings.substitution_groups_path)
    resolved: list[ResolvedMember] = []
    unresolved: list[str] = []

    for grp in groups:
        gname = grp["name"]
        etype = grp.get("entity_type", "port")
        metric = grp.get("default_metric", top_default_metric)
        for member in grp.get("members", []):
            hit = _resolve_member(con, member, etype)
            label = member.get("portid") or member.get("match", "?")
            if hit is None:
                unresolved.append(f"{gname}: {label}")
                continue
            resolved.append(
                ResolvedMember(gname, etype, hit[0], hit[1], metric)
            )
    return resolved, unresolved


def detect_opportunities(con: duckdb.DuckDBPyConnection) -> int:
    """Populate ``signal`` rows of type 'opportunity'. Returns rows written."""
    members, _unresolved = resolve_groups(con)
    con.execute("DELETE FROM signal WHERE signal_type = 'opportunity'")
    if not members:
        return 0

    by_group: dict[str, list[ResolvedMember]] = {}
    for m in members:
        by_group.setdefault(m.group, []).append(m)

    bt = settings.bottleneck_z_threshold
    ot = settings.opportunity_z_threshold
    written = 0

    for gname, gmembers in by_group.items():
        if len(gmembers) < 2:
            continue
        ids = [m.entity_id for m in gmembers]
        name_by_id = {m.entity_id: m.entity_name for m in gmembers}
        metric = gmembers[0].metric
        group_entity_type = gmembers[0].entity_type
        placeholders = ",".join("?" for _ in ids)

        # One row per (entity, date) with its robust_z for this group's metric.
        # (`baseline` has no name column - names come from ``name_by_id``.)
        rows = con.execute(
            f"""
            SELECT b.obs_date, b.entity_id, b.value, b.expected, b.robust_z
            FROM baseline b
            WHERE b.metric = ?
              AND b.entity_id IN ({placeholders})
              AND b.n_obs >= ?
            ORDER BY b.obs_date
            """,
            [metric, *ids, settings.baseline_min_observations],
        ).fetchall()

        per_date: dict[dt.date, list[tuple]] = {}
        for r in rows:
            per_date.setdefault(r[0], []).append(r)

        for obs_date, day_rows in per_date.items():
            # row = (obs_date, entity_id, value, expected, robust_z)
            bottlenecked = [r for r in day_rows if r[4] <= -bt]
            if not bottlenecked:
                continue
            alternatives = [r for r in day_rows if r[4] >= -ot and r not in bottlenecked]
            if not alternatives:
                continue

            worst = min(bottlenecked, key=lambda r: r[4])
            worst_id, worst_val, worst_exp, worst_z = worst[1], worst[2], worst[3], worst[4]
            for alt in alternatives:
                _, alt_id, alt_val, alt_exp, alt_z = alt
                alt_name = name_by_id.get(alt_id, alt_id)
                lift_pct = None if not alt_exp else round(100 * (alt_val - alt_exp) / alt_exp, 1)
                detail = json.dumps(
                    {
                        "group": gname,
                        "metric": metric,
                        "congested_port": {
                            "entity_id": worst_id,
                            "name": name_by_id.get(worst_id, worst_id),
                            "robust_z": round(worst_z, 2),
                            "drop_pct_vs_expected": (
                                None if not worst_exp
                                else round(100 * (worst_val - worst_exp) / worst_exp, 1)
                            ),
                        },
                        "alternative_lift_pct_vs_expected": lift_pct,
                    }
                )
                con.execute(
                    """
                    INSERT OR REPLACE INTO signal
                        (signal_type, entity_type, entity_id, entity_name, metric, obs_date,
                         value, expected, robust_z, severity, detail)
                    VALUES ('opportunity', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        group_entity_type,
                        alt_id, alt_name, metric, obs_date,
                        alt_val, alt_exp, alt_z,
                        abs(worst_z),  # severity ranked by how bad the congested side is
                        detail,
                    ],
                )
                written += 1

    return written
```

### NARRATE WHILE TYPING

- `_resolve_member` turns a YAML line into a real PortWatch entity. Exact
  `portid` wins; otherwise a name `LIKE` with optional country, and when a
  pattern hits several ports we take the **highest-volume** one.
- The core loop, per group per date: is anyone **bottlenecked** (z ≤ −2)? If so,
  who in the same group is **not degraded** (z ≥ −1.5)? Every such pair becomes
  an opportunity row.
- **Severity is the congested side's z-score**, not the alternative's — we rank
  opportunities by how badly the reroute is needed.
- `detail` carries both ends: which port is jammed and how far the alternative
  is running above its own norm.

### TYPE — `src/logjam/analytics/recovery.py`

```python
"""Recovery status: is a disruption still ongoing, or has flow returned to normal?

Answers the question the bottleneck feed cannot: for a named port or chokepoint,
where does throughput sit *now* relative to a year ago, and which way is it
trending? Built on the ``baseline.pct_of_yoy`` column.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import duckdb

from logjam.config import settings

# The "headline" total metric per entity type - what a human means by
# "traffic through Hormuz" or "activity at Rotterdam".
_DEFAULT_METRICS = ("n_total", "portcalls", "import", "export")

Verdict = str  # one of the constants below
RECOVERED: Verdict = "recovered"
PARTIAL: Verdict = "partial recovery"
ONGOING: Verdict = "disruption ongoing"
SEVERE: Verdict = "severe disruption ongoing"
NO_HISTORY: Verdict = "insufficient year-ago history"


@dataclass(frozen=True)
class RecoveryRow:
    entity_type: str
    entity_id: str
    entity_name: str
    metric: str
    as_of: dt.date
    value: float
    expected_yoy: float | None
    pct_of_yoy: float | None
    pct_of_yoy_prior: float | None  # ~4 weeks earlier, for trend
    verdict: Verdict

    @property
    def trend(self) -> str:
        if self.pct_of_yoy is None or self.pct_of_yoy_prior is None:
            return "n/a"
        delta = self.pct_of_yoy - self.pct_of_yoy_prior
        if abs(delta) < 0.05:
            return "flat"
        return "improving" if delta > 0 else "worsening"


def _verdict(pct: float | None) -> Verdict:
    if pct is None:
        return NO_HISTORY
    if pct >= 1 - settings.recovery_tolerance:
        return RECOVERED
    if pct >= 0.75:
        return PARTIAL
    if pct >= 0.4:
        return ONGOING
    return SEVERE


def recovery_status(
    con: duckdb.DuckDBPyConnection,
    search: str,
    *,
    metrics: tuple[str, ...] = _DEFAULT_METRICS,
    prior_days: int = 28,
) -> list[RecoveryRow]:
    """Recovery status for every entity whose name matches ``search``.

    ``search`` is a case-insensitive substring of the port / chokepoint name.
    Each figure is the median over a trailing ``recovery_window_days`` window
    that ends ``recovery_trailing_exclude_days`` before the last available date
    (PortWatch under-reports its most recent days). ``pct_of_yoy_prior`` is the
    same window shifted ``prior_days`` back, for the trend column.

    Returns one row per (entity, metric), worst (lowest pct_of_yoy) first.
    """
    like = f"%{search}%"
    metric_list = ",".join(f"'{m}'" for m in metrics)
    win = settings.recovery_window_days
    excl = settings.recovery_trailing_exclude_days

    rows = con.execute(
        f"""
        WITH names AS (
            SELECT entity_type, entity_id, any_value(entity_name) AS entity_name
            FROM observation GROUP BY entity_type, entity_id
        ),
        matched AS (
            SELECT DISTINCT b.entity_type, b.entity_id, b.metric
            FROM baseline b
            JOIN names o USING (entity_type, entity_id)
            WHERE lower(o.entity_name) LIKE lower(?)
              AND b.metric IN ({metric_list})
        ),
        bounds AS (  -- trailing evaluation window per series
            SELECT m.entity_type, m.entity_id, m.metric,
                   max(b.obs_date) - ? AS win_end,
                   max(b.obs_date) - ? - ? AS win_start
            FROM matched m
            JOIN baseline b USING (entity_type, entity_id, metric)
            GROUP BY 1, 2, 3
        ),
        agg AS (
            SELECT x.entity_type, x.entity_id, x.metric,
                   max(b.obs_date) AS as_of,
                   median(b.value) AS value,
                   median(b.expected_yoy) AS expected_yoy,
                   median(b.pct_of_yoy) AS pct_of_yoy,
                   median(pr.pct_of_yoy) AS pct_of_yoy_prior
            FROM bounds x
            JOIN baseline b
              ON b.entity_type = x.entity_type AND b.entity_id = x.entity_id
             AND b.metric = x.metric
             AND b.obs_date BETWEEN x.win_start AND x.win_end
            LEFT JOIN baseline pr
              ON pr.entity_type = x.entity_type AND pr.entity_id = x.entity_id
             AND pr.metric = x.metric AND pr.obs_date = b.obs_date - ?
            GROUP BY 1, 2, 3
        )
        SELECT a.entity_type, a.entity_id, n.entity_name, a.metric, a.as_of,
               a.value, a.expected_yoy, a.pct_of_yoy, a.pct_of_yoy_prior
        FROM agg a
        JOIN names n USING (entity_type, entity_id)
        ORDER BY a.pct_of_yoy NULLS LAST
        """,
        [like, excl, excl, win - 1, prior_days],
    ).fetchall()

    out: list[RecoveryRow] = []
    for (etype, eid, ename, metric, as_of, value, exp_yoy, pct, pct_prior) in rows:
        out.append(
            RecoveryRow(
                entity_type=etype,
                entity_id=eid,
                entity_name=ename,
                metric=metric,
                as_of=as_of,
                value=value,
                expected_yoy=exp_yoy,
                pct_of_yoy=pct,
                pct_of_yoy_prior=pct_prior,
                verdict=_verdict(pct),
            )
        )
    return out
```

### NARRATE WHILE TYPING

- This is a **query tool**, not a detector — you name a place, it tells you
  where throughput sits versus a year ago and which way it's moving.
- Everything is a **median over a trailing week**, ending a couple of days back
  because PortWatch under-reports its most recent days. `pct_of_yoy_prior` is
  the same window a month earlier — that's the `trend` column.
- `_verdict` buckets `pct_of_yoy`: within 20% of last year is "recovered", down
  to 75% "partial", to 40% "ongoing", below that "severe."
- **The honest caveat** goes in the README: this compares to *a year ago*, not
  *pre-crisis*. For an event under a year old — the 2026 Hormuz case — that's
  exactly right. Older than that and both numbers are depressed and it reads
  "recovered" when it means "stably degraded."

### TYPE — `src/logjam/analytics/__init__.py`

```python
"""Analytics: baselines, bottleneck detection, opportunity scoring.

Method in one paragraph
-----------------------
For every ``(entity, metric)`` time series we compute a *robust* rolling
baseline - trailing median and MAD (median absolute deviation) - and express
each day as a robust z-score ``(value - median) / (1.4826 * MAD)``. Median/MAD
rather than mean/std because port-call counts are spiky and we do not want a
single storm day to inflate the band for weeks. A large negative z on a
throughput or chokepoint-transit metric == flow is blocked (bottleneck). A
group-relative positive z on an alternative port == spare capacity is moving
(opportunity).
"""

from logjam.analytics.baseline import compute_baselines
from logjam.analytics.detect import detect_bottlenecks
from logjam.analytics.opportunity import detect_opportunities
from logjam.analytics.recovery import recovery_status

__all__ = [
    "compute_baselines",
    "detect_bottlenecks",
    "detect_opportunities",
    "recovery_status",
]
```

### RUN

```bash
uv run python -c "
from logjam.store import connect
from logjam.analytics import detect_bottlenecks, detect_opportunities
con = connect()
print('bottlenecks:', detect_bottlenecks(con))
print('opportunities:', detect_opportunities(con))
"
```

> The analytics all work off the same two tables. Now let's give a human a way
> to drive it.

---

## Segment 7 — Pipeline + CLI, run it for real

**Runtime:** 6 min
**Goal:** one `refresh()` that chains the whole thing, and a `logjam` command.
**Files:** `src/logjam/pipeline.py`, `cli.py`, `scripts/refresh.py`

### TYPE — `src/logjam/pipeline.py`

```python
"""End-to-end refresh: ingest -> store -> baseline -> detect -> opportunities."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

import duckdb

from logjam.analytics.baseline import compute_baselines
from logjam.analytics.detect import detect_bottlenecks
from logjam.analytics.opportunity import detect_opportunities
from logjam.ingest.portwatch import default_since, fetch_portwatch, month_starts
from logjam.store.db import connect, init_schema, latest_observation_date
from logjam.store.loaders import upsert_observations

# Above this span we ingest month-by-month so a first backfill (potentially
# ~1M rows/year) never has to sit in memory all at once.
_CHUNK_THRESHOLD_DAYS = 75


@dataclass
class RefreshResult:
    since: dt.date
    observations_written: int
    baseline_rows: int
    bottlenecks: int
    opportunities: int


def _ingest(
    con: duckdb.DuckDBPyConnection, since: dt.date, *, progress: Callable[[str], None]
) -> int:
    """Fetch PortWatch data from ``since`` to today and upsert it. Returns rows."""
    today = dt.date.today()
    written = 0

    if (today - since).days <= _CHUNK_THRESHOLD_DAYS:
        progress(f"fetching {since} .. {today}")
        written += upsert_observations(con, fetch_portwatch(since=since), source="portwatch")
        return written

    bounds = [*month_starts(since, today), today + dt.timedelta(days=1)]
    for start, end in zip(bounds, bounds[1:], strict=False):
        chunk_since = max(start, since)
        progress(f"fetching {chunk_since} .. {end}")
        tidy = fetch_portwatch(since=chunk_since, until=end)
        written += upsert_observations(con, tidy, source="portwatch")
    return written


def refresh(
    *,
    full_backfill: bool = False,
    progress: Callable[[str], None] = lambda _msg: None,
) -> RefreshResult:
    """Run the whole pipeline. Safe to call repeatedly (idempotent upserts).

    Args:
        full_backfill: ignore stored data and pull ``initial_backfill_days``.
        progress: optional callback for human-readable status lines.
    """
    con = connect()
    try:
        init_schema(con)
        latest = None if full_backfill else latest_observation_date(con)
        since = default_since(latest)

        written = _ingest(con, since, progress=progress)

        progress("computing baselines")
        baseline_rows = compute_baselines(con)
        progress("detecting bottlenecks")
        bottlenecks = detect_bottlenecks(con)
        progress("detecting opportunities")
        opportunities = detect_opportunities(con)

        return RefreshResult(
            since=since,
            observations_written=written,
            baseline_rows=baseline_rows,
            bottlenecks=bottlenecks,
            opportunities=opportunities,
        )
    finally:
        con.close()
```

### NARRATE WHILE TYPING

- `refresh()` is the whole product in one function: pick a start date, ingest,
  recompute baselines, detect, score. Idempotent — run it as often as you like.
- The chunking: anything over ~75 days ingests **month by month** so a first
  900-day backfill never holds a million rows in memory at once. `month_starts`
  from Segment 3 does the boundary math.
- `progress` is a plain callback — the CLI passes `rich`'s logger, CI passes
  `print`, tests pass nothing.

### TYPE — `src/logjam/cli.py`

```python
"""Command-line interface.

    logjam refresh [--full]         pull data + recompute everything
    logjam bottlenecks [--days 14]  list recent bottleneck signals
    logjam opportunities [--days 14] list recent reroute opportunities
    logjam ports --search "long beach"   look up PortWatch port ids
    logjam status                   what's in the local database
"""

from __future__ import annotations

import datetime as dt

import typer
from rich.console import Console
from rich.table import Table

from logjam.analytics.recovery import recovery_status
from logjam.config import settings
from logjam.pipeline import refresh as run_refresh
from logjam.store.db import connect, init_schema

app = typer.Typer(add_completion=False, help="Logistics bottleneck & opportunity identifier.")
console = Console()


@app.command()
def refresh(
    full: bool = typer.Option(False, "--full", help="Ignore stored data; backfill."),
) -> None:
    """Ingest the latest PortWatch data and recompute signals."""
    res = run_refresh(full_backfill=full, progress=lambda m: console.log(m))
    console.print(
        f"[green]Done.[/green] since={res.since}  observations={res.observations_written:,}  "
        f"baseline_rows={res.baseline_rows:,}  "
        f"bottlenecks={res.bottlenecks:,}  opportunities={res.opportunities:,}"
    )


def _signal_table(signal_type: str, days: int, limit: int) -> Table:
    cutoff = dt.date.today() - dt.timedelta(days=days)
    con = connect(read_only=True)
    try:
        rows = con.execute(
            """
            SELECT obs_date, entity_type, entity_name, metric,
                   value, expected, robust_z, severity, detail
            FROM signal
            WHERE signal_type = ? AND obs_date >= ?
            ORDER BY obs_date DESC, severity DESC
            LIMIT ?
            """,
            [signal_type, cutoff, limit],
        ).fetchall()
    finally:
        con.close()

    table = Table(title=f"{signal_type.title()} signals (last {days}d)")
    for col in ("date", "type", "entity", "metric", "value", "expected", "z", "detail"):
        table.add_column(col)
    for (d, et, name, metric, val, exp, z, _sev, detail) in rows:
        table.add_row(
            str(d), et, name or "?", metric,
            f"{val:,.0f}", f"{exp:,.0f}", f"{z:+.1f}",
            (detail or "")[:80],
        )
    return table


@app.command()
def bottlenecks(days: int = 14, limit: int = 40) -> None:
    """List recent bottleneck signals (flow blocked vs baseline)."""
    console.print(_signal_table("bottleneck", days, limit))


@app.command()
def opportunities(days: int = 14, limit: int = 40) -> None:
    """List recent opportunity signals (alternative with headroom in a substitution group)."""
    console.print(_signal_table("opportunity", days, limit))


@app.command()
def ports(
    search: str = typer.Option(..., "--search", "-s", help="Substring of the port name."),
) -> None:
    """Look up PortWatch entity ids by name."""
    con = connect(read_only=True)
    try:
        rows = con.execute(
            """
            SELECT entity_type, entity_id, any_value(entity_name), any_value(iso3),
                   count(*) AS n, max(obs_date) AS last_seen
            FROM observation
            WHERE lower(entity_name) LIKE lower(?)
            GROUP BY entity_type, entity_id
            ORDER BY n DESC
            LIMIT 50
            """,
            [f"%{search}%"],
        ).fetchall()
    finally:
        con.close()
    table = Table(title=f'ports matching "{search}"')
    for col in ("type", "entity_id", "name", "iso3", "last_seen"):
        table.add_column(col)
    for (et, eid, name, iso3, _n, last_seen) in rows:
        table.add_row(et, eid, name, iso3 or "", str(last_seen))
    console.print(table)


@app.command()
def recovery(
    search: str = typer.Option(
        ..., "--search", "-s", help="Substring of the port/chokepoint name."
    ),
) -> None:
    """Is a disruption still ongoing? Current throughput vs the same period a year ago.

    Example: `logjam recovery -s hormuz`
    """
    con = connect(read_only=True)
    try:
        rows = recovery_status(con, search)
    finally:
        con.close()

    if not rows:
        console.print(f'No baseline rows match "{search}". Try `logjam ports -s {search}`.')
        return

    table = Table(title=f'Recovery status: "{search}"')
    for col in ("entity", "metric", "as of", "now", "yr-ago", "% of normal", "trend", "verdict"):
        table.add_column(col)
    style = {
        "recovered": "green",
        "partial recovery": "yellow",
        "disruption ongoing": "red",
        "severe disruption ongoing": "bold red",
        "insufficient year-ago history": "dim",
    }
    for r in rows:
        pct = "-" if r.pct_of_yoy is None else f"{r.pct_of_yoy * 100:.0f}%"
        yr = "-" if r.expected_yoy is None else f"{r.expected_yoy:,.0f}"
        table.add_row(
            r.entity_name, r.metric, str(r.as_of), f"{r.value:,.0f}", yr, pct, r.trend,
            f"[{style.get(r.verdict, 'white')}]{r.verdict}[/]",
        )
    console.print(table)
    console.print(
        "[dim]% of normal = today's value / median around the same date ~1 year "
        "earlier. 'trend' compares with ~4 weeks ago.[/dim]"
    )


@app.command()
def status() -> None:
    """Show what the local database currently holds."""
    # Read-write so a brand-new database gets its schema created.
    con = connect()
    try:
        init_schema(con)
        obs = con.execute(
            "SELECT count(*), min(obs_date), max(obs_date), "
            "count(DISTINCT entity_id) FROM observation"
        ).fetchone()
        sigs = con.execute(
            "SELECT signal_type, count(*) FROM signal GROUP BY signal_type"
        ).fetchall()
    finally:
        con.close()
    console.print(f"db: {settings.db_path}")
    console.print(
        f"observations: {obs[0]:,}  dates: {obs[1]} .. {obs[2]}  entities: {obs[3]:,}"
    )
    for (stype, n) in sigs:
        console.print(f"  {stype}: {n:,}")


if __name__ == "__main__":
    app()
```

### NARRATE WHILE TYPING

- `typer` gives us subcommands and `--flags` from type hints; `rich.Table`
  makes the output readable.
- Read commands open the connection **read-only** — you can query while a
  refresh is running.
- `_signal_table` is shared by `bottlenecks` and `opportunities` — same shape,
  different `signal_type`.
- `recovery` is the one with colour: green for recovered, bold red for severe.

### TYPE — `scripts/refresh.py`

```python
#!/usr/bin/env python
"""Cron entry point: `python scripts/refresh.py [--full]`.

Kept as a thin wrapper so CI / cron does not depend on the console-script being
installed on PATH.
"""

from __future__ import annotations

import argparse
import sys

from logjam.pipeline import refresh


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="Ignore stored data; backfill.")
    args = parser.parse_args()

    res = refresh(full_backfill=args.full, progress=lambda m: print(f"... {m}", flush=True))
    print(
        f"since={res.since} observations={res.observations_written} "
        f"baseline_rows={res.baseline_rows} "
        f"bottlenecks={res.bottlenecks} opportunities={res.opportunities}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### RUN

```bash
uv run logjam refresh --full      # first run: backfill + compute (~10 min)
uv run logjam status
uv run logjam recovery --search "hormuz"
uv run logjam opportunities --days 30
```

### SAY

> There it is. `recovery --search hormuz` — container transits at a single-digit
> percentage of a year ago, verdict severe, and the opportunity feed points at
> the Indian west coast and Salalah. From a keyless public API to an actionable
> reroute signal.

---

## Segment 8 — Tests, CI, the report

**Runtime:** 6 min
**Goal:** lock the behaviour in, automate the weekly refresh, ship a finished brief.
**Files:** `tests/conftest.py`, `tests/test_portwatch_ingest.py`,
`tests/test_analytics.py`, `.github/workflows/refresh.yml`

### SAY

> Two test files: the ingest transform with the network mocked, and the
> analytics over synthetic series where we know the right answer. Then a weekly
> GitHub Action so the data refreshes itself.

### TYPE — `tests/conftest.py`

```python
from __future__ import annotations

import duckdb
import pytest

from logjam.store.db import init_schema


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    init_schema(c)
    yield c
    c.close()
```

### TYPE — `tests/test_portwatch_ingest.py`

```python
"""Ingest transform tests - no network, ArcGIS responses are mocked."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx

from logjam.config import settings
from logjam.ingest.portwatch import (
    TIDY_COLUMNS,
    _parse_arcgis_date,
    _where_range,
    fetch_portwatch,
    month_starts,
)

# This layer returns ISO strings; other ArcGIS services use epoch ms - test both.
_D1 = "2024-01-15"
_D2 = int(dt.datetime(2024, 1, 16, tzinfo=dt.UTC).timestamp() * 1000)


def test_parse_arcgis_date_handles_iso_string_and_epoch_ms() -> None:
    assert _parse_arcgis_date("2026-08-21") == dt.date(2026, 8, 21)
    assert _parse_arcgis_date(_D2) == dt.date(2024, 1, 16)
    assert _parse_arcgis_date(None) is None
    assert _parse_arcgis_date("") is None


def test_where_range_is_half_open() -> None:
    assert _where_range(None, None) == "1=1"
    assert _where_range(dt.date(2026, 1, 1), None) == "date >= DATE '2026-01-01'"
    assert (
        _where_range(dt.date(2026, 1, 1), dt.date(2026, 2, 1))
        == "date >= DATE '2026-01-01' AND date < DATE '2026-02-01'"
    )


def test_month_starts_spans_range_inclusive() -> None:
    starts = month_starts(dt.date(2025, 11, 15), dt.date(2026, 2, 3))
    assert starts == [
        dt.date(2025, 11, 1),
        dt.date(2025, 12, 1),
        dt.date(2026, 1, 1),
        dt.date(2026, 2, 1),
    ]


def _ports_page() -> dict:
    return {
        "features": [
            {
                "attributes": {
                    "date": _D1, "portid": "port1", "portname": "Los Angeles",
                    "country": "United States", "ISO3": "USA",
                    "portcalls_container": 30, "portcalls": 45,
                    "import_container": 1000.5, "export": 800.0,
                    "ObjectId": 1,
                }
            },
            {
                "attributes": {
                    "date": _D2, "portid": "port1", "portname": "Los Angeles",
                    "country": "United States", "ISO3": "USA",
                    "portcalls_container": 5, "portcalls": 9,
                    "import_container": 120.0, "export": 90.0,
                    "ObjectId": 2,
                }
            },
        ]
    }


def _chokepoints_page() -> dict:
    return {
        "features": [
            {
                "attributes": {
                    "date": _D1, "portid": "chokepoint1", "portname": "Strait of Hormuz",
                    "n_tanker": 40, "n_total": 55, "capacity_total": 1_000_000,
                    "ObjectId": 1,
                }
            }
        ]
    }


@respx.mock
def test_fetch_portwatch_returns_tidy_long_frame() -> None:
    respx.get(settings.portwatch_ports_url).mock(
        return_value=httpx.Response(200, json=_ports_page())
    )
    respx.get(settings.portwatch_chokepoints_url).mock(
        return_value=httpx.Response(200, json=_chokepoints_page())
    )

    df = fetch_portwatch(since=dt.date(2024, 1, 1))

    assert list(df.columns) == TIDY_COLUMNS
    assert set(df["entity_type"]) == {"port", "chokepoint"}

    la_containers = df[
        (df.entity_id == "port1")
        & (df.metric == "portcalls_container")
    ].set_index("date")["value"]
    assert la_containers.loc[dt.date(2024, 1, 15)] == 30
    assert la_containers.loc[dt.date(2024, 1, 16)] == 5

    # Chokepoint rows have no country/iso3 - should be present but null.
    hormuz = df[df.entity_id == "chokepoint1"]
    assert hormuz["country"].isna().all()
    assert (hormuz["metric"] == "n_tanker").any()


@respx.mock
def test_fetch_portwatch_raises_on_arcgis_error_body() -> None:
    respx.get(settings.portwatch_ports_url).mock(
        return_value=httpx.Response(200, json={"error": {"code": 400, "message": "bad"}})
    )
    respx.get(settings.portwatch_chokepoints_url).mock(
        return_value=httpx.Response(200, json={"features": []})
    )
    with pytest.raises(RuntimeError, match="ArcGIS error"):
        fetch_portwatch(since=dt.date(2024, 1, 1))
```

### TYPE — `tests/test_analytics.py`

```python
"""Store + baseline + detection over synthetic data."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from logjam.analytics.baseline import compute_baselines
from logjam.analytics.detect import detect_bottlenecks
from logjam.analytics.recovery import SEVERE, recovery_status
from logjam.store.loaders import upsert_observations


def _series(entity_id: str, name: str, values: list[float], metric: str) -> pd.DataFrame:
    start = dt.date(2024, 1, 1)
    return pd.DataFrame(
        {
            "entity_type": "port",
            "entity_id": entity_id,
            "entity_name": name,
            "country": "Testland",
            "iso3": "TST",
            "date": [start + dt.timedelta(days=i) for i in range(len(values))],
            "metric": metric,
            "value": values,
        }
    )


def test_upsert_is_idempotent(con) -> None:
    df = _series("port1", "Alpha", [10.0] * 30, "portcalls_container")
    upsert_observations(con, df)
    upsert_observations(con, df)  # same window again
    n = con.execute("SELECT count(*) FROM observation").fetchone()[0]
    assert n == 30


def test_bottleneck_flagged_on_throughput_collapse(con) -> None:
    # 60 stable days at ~100, then a hard drop to 10.
    values = [100.0, 98.0, 102.0, 101.0, 99.0] * 12 + [10.0]
    upsert_observations(con, _series("port1", "Alpha", values, "portcalls_container"))

    assert compute_baselines(con) > 0
    flagged = detect_bottlenecks(con)
    assert flagged >= 1

    row = con.execute(
        "SELECT metric, robust_z FROM signal "
        "WHERE signal_type = 'bottleneck' ORDER BY obs_date DESC LIMIT 1"
    ).fetchone()
    assert row[0] == "portcalls_container"
    assert row[1] < 0  # collapse, not surge


def test_stable_series_produces_no_bottleneck(con) -> None:
    values = [100.0, 99.0, 101.0, 100.0, 100.0] * 14
    upsert_observations(con, _series("port2", "Beta", values, "portcalls"))
    compute_baselines(con)
    assert detect_bottlenecks(con) == 0


def _long_series(
    entity_id: str, name: str, values: list[float], metric: str
) -> pd.DataFrame:
    """Like _series but starting far enough back for a year-over-year lookup."""
    start = dt.date.today() - dt.timedelta(days=len(values))
    return pd.DataFrame(
        {
            "entity_type": "chokepoint",
            "entity_id": entity_id,
            "entity_name": name,
            "country": None,
            "iso3": None,
            "date": [start + dt.timedelta(days=i) for i in range(len(values))],
            "metric": metric,
            "value": values,
        }
    )


def test_sustained_collapse_still_flags_via_year_over_year(con) -> None:
    # ~14 months normal at ~60, then ~5 months collapsed at ~4 and holding.
    # The 56-day short baseline heals around the new low; YoY must keep flagging.
    normal = [60.0, 58.0, 62.0, 59.0, 61.0] * 84       # 420 days
    collapsed = [4.0, 3.0, 5.0, 4.0, 4.0] * 30          # 150 days
    upsert_observations(con, _long_series("chokepoint6", "Strait of Hormuz",
                                          normal + collapsed, "n_total"))
    compute_baselines(con)

    latest = con.execute(
        "SELECT robust_z, robust_z_yoy, pct_of_yoy FROM baseline "
        "WHERE metric='n_total' ORDER BY obs_date DESC LIMIT 1"
    ).fetchone()
    assert latest[0] > -2.0            # short baseline has healed
    assert latest[1] <= -2.0           # YoY still deeply negative
    assert latest[2] < 0.2             # running below 20% of a year ago

    assert detect_bottlenecks(con) >= 1
    trig = con.execute(
        "SELECT detail FROM signal WHERE signal_type='bottleneck' "
        "ORDER BY obs_date DESC LIMIT 1"
    ).fetchone()[0]
    assert '"trigger": "yoy"' in trig

    rec = recovery_status(con, "hormuz")
    assert rec and rec[0].verdict == SEVERE
    assert rec[0].pct_of_yoy is not None and rec[0].pct_of_yoy < 0.2
```

### NARRATE WHILE TYPING

- `respx` intercepts the `httpx` calls — the ingest tests never touch the
  network, so they're fast and deterministic.
- The analytics tests build synthetic series where we know the answer: a flat
  line then a cliff **must** flag; a flat line **must not**.
- The last test is the important one — it proves the year-over-year baseline
  keeps a months-long collapse visible after the short baseline has "healed"
  around the new low, and that `recovery` calls it "severe."

### TYPE — `.github/workflows/refresh.yml`

```yaml
name: refresh

# PortWatch updates weekly on Tuesdays ~09:00 ET (13:00-14:00 UTC).
# Run a few hours later, plus a manual trigger.
on:
  schedule:
    - cron: "0 18 * * 2"
  workflow_dispatch:
    inputs:
      full:
        description: "Full backfill"
        type: boolean
        default: false

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Sync deps
        run: uv sync --extra dev

      # The committed DuckDB file is the state store between runs. It is
      # git-ignored for local dev; in CI we cache it instead so history
      # accumulates without bloating the repo.
      - name: Restore database
        uses: actions/cache@v4
        with:
          path: data/logjam.duckdb
          key: bottleneck-db-${{ github.run_id }}
          restore-keys: bottleneck-db-

      - name: Refresh
        run: uv run python scripts/refresh.py ${{ inputs.full && '--full' || '' }}

      - name: Upload signals artifact
        run: uv run logjam opportunities --days 30 > opportunities.txt || true
      - uses: actions/upload-artifact@v4
        with:
          name: signals
          path: opportunities.txt
```

### NARRATE WHILE TYPING

- Runs every Tuesday afternoon UTC, a few hours after PortWatch's weekly update,
  plus a manual button.
- The DuckDB file is **cached**, not committed — `actions/cache` with a
  restore-key prefix means each run picks up the last run's database and adds to
  it. History accumulates, repo stays small.

### RUN

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

### SAY

> Green across the board. The last piece is turning a query into something you
> can hand to someone — `scripts/reports/hormuz_container_2026.py` re-derives
> every figure in the brief straight from the DuckDB store, writes them to JSON,
> and the HTML report reads that JSON. Nothing hand-transcribed, fully
> reproducible. And that's the project: free public data in, a defensible
> reroute call out.

### DO — the closing shot

```bash
uv run python scripts/reports/hormuz_container_2026.py
git add -A && git commit -m "logjam: PortWatch vertical slice"
```

---

## Recap slide

1. **Scaffold** — `uv`, `src/` layout, every tunable in `config.py`.
2. **ArcGIS client** — one generator that pages any FeatureServer.
3. **PortWatch adapter** — two wide layers → one tidy long frame; fixed 8-column contract.
4. **DuckDB store** — three tables, idempotent DELETE-then-INSERT upsert.
5. **Baseline** — robust rolling median/MAD z-score, plus a year-over-year z-score.
6. **Detection** — negative-tail z (short OR yoy) → bottleneck; substitution-group divergence → opportunity; `pct_of_yoy` → recovery verdict.
7. **Pipeline + CLI** — one `refresh()`, a `typer` app, run it for real.
8. **Tests + CI + report** — mocked ingest, synthetic analytics, weekly Action, reproducible brief.
