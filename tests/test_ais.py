"""AISStream adapter: message parsing, geofencing, and the raw -> tidy reducer.

No network and no live stream - AISStream envelopes are hand-built and the raw
capture is a Parquet file written into a temp dir.
"""

from __future__ import annotations

import datetime as dt

import duckdb
import pandas as pd

from logjam.analytics.ais_reduce import reduce_day
from logjam.ingest import ais_zones
from logjam.ingest.ais_zones import Zone, load_zones, subscription_boxes
from logjam.ingest.aisstream import RAW_COLUMNS, _row_from_message, build_subscription

# Jebel Ali, from the committed PortWatch coordinate table.
_JA_LAT, _JA_LON = 24.999, 55.078


def _position_envelope(mmsi: int, lat: float, lon: float, sog: float, nav: int = 0) -> dict:
    return {
        "MessageType": "PositionReport",
        "MetaData": {
            "MMSI": mmsi,
            "ShipName": f"SHIP {mmsi}",
            "latitude": lat,
            "longitude": lon,
            "time_utc": "2026-08-31 12:00:00.000000000 +0000 UTC",
        },
        "Message": {
            "PositionReport": {
                "UserID": mmsi,
                "Latitude": lat,
                "Longitude": lon,
                "Sog": sog,
                "Cog": 90.0,
                "NavigationalStatus": nav,
            }
        },
    }


def test_build_subscription_shape() -> None:
    sub = build_subscription("KEY", [[[10.0, 40.0], [20.0, 50.0]]])
    assert sub["APIKey"] == "KEY"
    assert sub["BoundingBoxes"] == [[[10.0, 40.0], [20.0, 50.0]]]
    assert sub["FilterMessageTypes"] == ["PositionReport", "ShipStaticData"]


def test_row_from_message_parses_position_and_rejects_junk() -> None:
    now = dt.datetime(2026, 8, 31, 12, 0, tzinfo=dt.UTC)
    row = _row_from_message(_position_envelope(111, 25.0, 55.0, 0.1, nav=1), now)
    assert row is not None
    assert set(row) == set(RAW_COLUMNS)
    assert row["mmsi"] == 111
    assert row["nav_status"] == 1
    assert row["msg_type"] == "PositionReport"

    assert _row_from_message({"MessageType": "BaseStationReport"}, now) is None
    assert _row_from_message({"MessageType": "PositionReport", "Message": {}}, now) is None


def test_row_from_message_reads_ship_static_data() -> None:
    now = dt.datetime(2026, 8, 31, tzinfo=dt.UTC)
    env = {
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": 222, "latitude": 25.0, "longitude": 55.0},
        "Message": {"ShipStaticData": {"UserID": 222, "Type": 70, "Name": "BOX BOAT"}},
    }
    row = _row_from_message(env, now)
    assert row["ship_type"] == 70
    assert row["ship_name"] == "BOX BOAT"


def test_zone_contains_circle_and_box() -> None:
    circle = Zone("port", "port1", "P", 25.0, 55.0, radius_km=25.0)
    assert circle.contains(25.0, 55.0)
    assert circle.contains(25.1, 55.0)          # ~11 km north
    assert not circle.contains(25.5, 55.0)      # ~55 km north

    box = Zone("chokepoint", "chokepoint1", "C", 26.0, 56.0, half_deg=0.35)
    assert box.contains(26.3, 56.3)
    assert not box.contains(26.5, 56.0)


def test_subscription_boxes_are_wellformed() -> None:
    boxes = subscription_boxes()
    assert boxes
    for (lo_lat, lo_lon), (hi_lat, hi_lon) in boxes:
        assert lo_lat < hi_lat and lo_lon < hi_lon


def test_load_zones_resolves_watchlist_and_chokepoints() -> None:
    load_zones.cache_clear()
    zones = load_zones()
    by_name = {z.entity_name.lower(): z for z in zones}
    assert any("jebel ali" in n for n in by_name)
    assert any(z.entity_type == "chokepoint" and z.entity_id == "chokepoint6" for z in zones)
    # every port zone is a circle, every chokepoint zone is a box
    for z in zones:
        assert (z.radius_km is None) != (z.half_deg is None)


def _write_raw(tmp_path, date: dt.date, rows: list[dict]) -> None:
    part = tmp_path / f"dt={date.isoformat()}"
    part.mkdir(parents=True)
    frame = pd.DataFrame(rows)
    con = duckdb.connect()
    try:
        con.register("f", frame)
        con.execute(f"COPY f TO '{part / 'cap-1.parquet'}' (FORMAT PARQUET)")
    finally:
        con.close()


def test_reduce_day_counts_anchored_and_moving(tmp_path, con, monkeypatch) -> None:
    from logjam.config import settings

    monkeypatch.setattr(settings, "ais_raw_dir", tmp_path)
    monkeypatch.setattr(settings, "ais_min_messages_per_day", 1)
    load_zones.cache_clear()
    ais_zones._places.cache_clear()

    date = dt.date(2026, 8, 31)
    rows = []
    # 3 vessels sitting still inside the Jebel Ali catchment -> a queue of 3
    for mmsi in (1, 2, 3):
        for _ in range(4):
            rows.append(
                {"mmsi": mmsi, "lat": _JA_LAT + 0.02, "lon": _JA_LON, "sog": 0.1,
                 "nav_status": 1, "msg_type": "PositionReport"}
            )
    # 2 vessels under way through the catchment
    for mmsi in (4, 5):
        for _ in range(4):
            rows.append(
                {"mmsi": mmsi, "lat": _JA_LAT, "lon": _JA_LON + 0.05, "sog": 12.0,
                 "nav_status": 0, "msg_type": "PositionReport"}
            )
    # noise far away
    rows += [
        {"mmsi": 9, "lat": 0.0, "lon": 0.0, "sog": 5.0, "nav_status": 0,
         "msg_type": "PositionReport"}
    ] * 5
    _write_raw(tmp_path, date, rows)

    written = reduce_day(con, date)
    assert written > 0

    got = {
        (m, metric): v
        for m, metric, v in con.execute(
            "SELECT entity_name, metric, value FROM observation "
            "WHERE source = 'aisstream' AND entity_name ILIKE '%jebel ali%'"
        ).fetchall()
    }
    ja = next(k[0] for k in got)
    assert got[(ja, "vessels_at_anchor")] == 3.0
    assert got[(ja, "vessels_moving")] == 2.0
