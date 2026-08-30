"""Ingest transform tests - no network, ArcGIS responses are mocked."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx

from bottleneck_logistics.config import settings
from bottleneck_logistics.ingest.portwatch import (
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
