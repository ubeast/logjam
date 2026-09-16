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

    # --- GDELT (news-attention signal) -----------------------------------
    # DOC 2.0 API: free, no key, but rate-limits hard (HTTP 429) and only serves
    # ~the last 3 months, so this is a collect-forward source - each refresh
    # pulls the trailing window and the store keeps history past the API window.
    gdelt_doc_url: str = "https://api.gdeltproject.org/api/v2/doc/doc"
    gdelt_request_pause_s: float = 5.0   # GDELT throttles per-IP at ~1 req / 5 s
    gdelt_timeout_s: float = 90.0        # healthy ~1-2 s/call; 10-60 s once throttled
    gdelt_max_lookback_days: int = 89    # DOC 2.0 only answers for roughly the last 3 months
    # A full pull is ~22 calls; at the 5 s pace that's ~2-3 min. Kept off the
    # every-`refresh` path so a throttled GDELT never slows a routine refresh.
    # Run `logjam news-fetch` (or its own CI cron), or set
    # LOGJAM_GDELT_ON_REFRESH=true to include it.
    gdelt_on_refresh: bool = False

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

    # --- AISStream (live AIS) --------------------------------------------
    # A push WebSocket, not a batch pull. We *sample* it: connect for
    # ``ais_sample_minutes``, capture position reports inside the zone bounding
    # boxes, disconnect, then reduce the raw capture to daily per-zone metrics
    # (vessels at anchor = a queue; vessels moving through a chokepoint = a
    # transit-rate cross-check on PortWatch). Free API key required - register
    # at https://aisstream.io and set ``LOGJAM_AISSTREAM_API_KEY``.
    aisstream_api_key: str = ""
    aisstream_url: str = "wss://stream.aisstream.io/v0/stream"
    ais_raw_dir: Path = Field(default=_PROJECT_ROOT / "data" / "ais_raw")
    ais_sample_minutes: int = 30
    # A vessel counts as "at anchor" below this speed over ground (knots) or with
    # an AIS navigational status of 1 (at anchor) / 5 (moored).
    ais_anchor_max_sog_kn: float = 1.0
    # Below this many raw messages for a day we skip the reduce - too thin a
    # sample to trust the counts.
    ais_min_messages_per_day: int = 200
    # Raw captures are deleted this many days after they have been reduced, so
    # data/ais_raw/ does not grow without bound. The reduced daily metrics stay
    # in the store; only the bulky raw Parquet is pruned.
    ais_raw_retention_days: int = 21

    @property
    def resources_dir(self) -> Path:
        return Path(__file__).resolve().parent / "resources"

    @property
    def substitution_groups_path(self) -> Path:
        return self.resources_dir / "substitution_groups.yaml"

    @property
    def ais_zones_path(self) -> Path:
        return self.resources_dir / "ais_zones.yaml"

    @property
    def gdelt_queries_path(self) -> Path:
        return self.resources_dir / "gdelt_queries.yaml"

    @property
    def carrier_routes_path(self) -> Path:
        return self.resources_dir / "carrier_routes.yaml"

    @property
    def geo_dir(self) -> Path:
        """Static geographic assets: PortWatch coordinates + the brief basemap."""
        return self.resources_dir / "geo"


settings = Settings()
