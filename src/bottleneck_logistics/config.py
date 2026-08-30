"""Runtime configuration.

All tunables live here so a follow-on developer has exactly one place to look.
Override any field with an environment variable prefixed ``BNL_`` (e.g.
``BNL_DB_PATH=/tmp/foo.duckdb``) or a ``.env`` file in the project root.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BNL_", env_file=".env", extra="ignore")

    # --- Storage -------------------------------------------------------------
    db_path: Path = Field(default=_PROJECT_ROOT / "data" / "bottleneck.duckdb")

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

    # --- Baseline / detection --------------------------------------------
    baseline_window_days: int = 56  # trailing window for the rolling baseline
    baseline_min_observations: int = 21  # require this many points or skip the series
    bottleneck_z_threshold: float = 2.0  # |robust z| above which a day is flagged
    # Direction that counts as a *bottleneck* per metric (a throughput collapse
    # or a chokepoint-transit collapse both mean "flow is blocked").
    # Opportunities look at the opposite tail.
    opportunity_z_threshold: float = 1.5

    @property
    def resources_dir(self) -> Path:
        return Path(__file__).resolve().parent / "resources"

    @property
    def substitution_groups_path(self) -> Path:
        return self.resources_dir / "substitution_groups.yaml"


settings = Settings()
