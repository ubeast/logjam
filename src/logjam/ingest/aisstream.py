"""AISStream.io ingestion adapter - the live-AIS sampler.

AISStream is a push WebSocket, not a batch endpoint, so this adapter *samples*
it: connect, subscribe to the zone regions, capture position + static messages
for a fixed number of minutes, disconnect, and append the raw rows to
date-partitioned Parquet under ``settings.ais_raw_dir``. Turning that raw
capture into the tidy per-zone daily metrics the store expects is a separate
step - :mod:`logjam.analytics.ais_reduce`.

Why sampling and not a daemon: it keeps the project a "clone and run" tool with
no always-on process. A 30-minute sample every few hours is enough to track how
many vessels are sitting at anchor off a port (a queue is a standing quantity)
and roughly how busy a chokepoint is; it is not a complete transit census.

Needs a free API key from https://aisstream.io - set ``LOGJAM_AISSTREAM_API_KEY``.

Coverage caveat: AISStream is *terrestrial* AIS (volunteer shore receivers), so
it covers Europe and North America well and the Persian Gulf / Red Sea / Arabian
Sea essentially not at all. The adapter is correct but the free feed cannot
populate the geography of the disruption briefs - re-point
``resources/ais_zones.yaml`` at a European port, or use a paid satellite-AIS
source. See ``docs/METHODOLOGY.md`` section 1a.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import websockets
from websockets.exceptions import WebSocketException

from logjam.config import settings
from logjam.ingest.ais_zones import subscription_boxes

# Columns of each raw Parquet file. One row per received AIS message we keep.
RAW_COLUMNS: list[str] = [
    "mmsi",
    "ship_name",
    "ship_type",       # AIS ship-type code (int) from ShipStaticData, else NA
    "lat",
    "lon",
    "sog",             # speed over ground, knots
    "cog",             # course over ground, degrees
    "nav_status",      # AIS navigational status code (0..15), else NA
    "msg_type",        # 'PositionReport' | 'ShipStaticData'
    "time_utc",        # message timestamp from AISStream MetaData
    "received_utc",    # when we received it
]

_FLUSH_EVERY = 50_000       # rows buffered before a Parquet flush, to bound memory
_KEEP_TYPES = ("PositionReport", "ShipStaticData")


def build_subscription(
    api_key: str,
    bounding_boxes: list[list[list[float]]],
    message_types: tuple[str, ...] = _KEEP_TYPES,
) -> dict[str, Any]:
    """The JSON the client sends immediately after connecting."""
    return {
        "APIKey": api_key,
        "BoundingBoxes": bounding_boxes,
        "FilterMessageTypes": list(message_types),
    }


def _first(d: dict[str, Any], *keys: str) -> Any:
    """First present, non-null value among ``keys`` (case variants differ by field)."""
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def _row_from_message(payload: dict[str, Any], now: dt.datetime) -> dict[str, Any] | None:
    """Flatten one AISStream envelope to a :data:`RAW_COLUMNS` row, or ``None``.

    AISStream normalises MMSI / name / position into ``MetaData`` but the exact
    key casing has drifted (``latitude`` vs ``Latitude``), so we check both and
    fall back to the typed ``Message`` body.
    """
    mtype = payload.get("MessageType")
    if mtype not in _KEEP_TYPES:
        return None
    meta = payload.get("MetaData") or {}
    body = (payload.get("Message") or {}).get(mtype) or {}

    mmsi = _first(meta, "MMSI") or _first(body, "UserID")
    if mmsi is None:
        return None

    lat = _first(meta, "latitude", "Latitude")
    if lat is None:
        lat = _first(body, "Latitude")
    lon = _first(meta, "longitude", "Longitude")
    if lon is None:
        lon = _first(body, "Longitude")

    name = (_first(meta, "ShipName", "Shipname") or _first(body, "Name") or "")
    return {
        "mmsi": int(mmsi),
        "ship_name": str(name).strip() or None,
        "ship_type": body.get("Type") if mtype == "ShipStaticData" else None,
        "lat": float(lat) if lat is not None else None,
        "lon": float(lon) if lon is not None else None,
        "sog": body.get("Sog"),
        "cog": body.get("Cog"),
        "nav_status": body.get("NavigationalStatus"),
        "msg_type": mtype,
        "time_utc": _first(meta, "time_utc", "TimeUtc"),
        "received_utc": now.isoformat(timespec="seconds"),
    }


def _flush(rows: list[dict[str, Any]], raw_dir: Path) -> int:
    """Write ``rows`` to ``raw_dir/dt=<date>/cap-<epoch>.parquet``. Returns rows written."""
    if not rows:
        return 0
    frame = pd.DataFrame(rows, columns=RAW_COLUMNS)
    written = 0
    for day, chunk in frame.groupby(frame["received_utc"].str.slice(0, 10)):
        part = raw_dir / f"dt={day}"
        part.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%f")
        con = duckdb.connect()
        try:
            con.register("chunk", chunk)
            con.execute(f"COPY chunk TO '{part / f'cap-{stamp}.parquet'}' (FORMAT PARQUET)")
        finally:
            con.close()
        written += len(chunk)
    rows.clear()
    return written


async def _run(minutes: float, *, progress: Callable[[str], None]) -> int:
    key = settings.aisstream_api_key
    if not key:
        raise RuntimeError(
            "No AISStream API key. Register (free) at https://aisstream.io and set "
            "LOGJAM_AISSTREAM_API_KEY (env or .env)."
        )

    boxes = subscription_boxes()
    sub = build_subscription(key, boxes)
    raw_dir = settings.ais_raw_dir
    buffer: list[dict[str, Any]] = []
    total = 0
    kept = 0

    progress(f"connecting to AISStream · {len(boxes)} regions · sampling {minutes:g} min")
    confirmed = False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + minutes * 60
    attempt = 0

    # AISStream drops long-lived connections every few minutes (a TCP reset, no
    # close frame). Reconnect and resubscribe until the wall-clock sample budget
    # is spent, flushing the buffer before every reconnect so a reset never
    # costs us the rows captured so far.
    while (remaining := deadline - loop.time()) > 0:
        attempt += 1
        try:
            async with websockets.connect(settings.aisstream_url, ping_interval=20) as ws:
                await ws.send(json.dumps(sub))
                try:
                    async with asyncio.timeout(remaining):
                        async for message in ws:
                            total += 1
                            try:
                                payload = json.loads(message)
                            except (ValueError, TypeError):
                                continue
                            err = payload.get("error") or payload.get("Error")
                            if err:
                                raise RuntimeError(f"AISStream rejected the subscription: {err}")
                            if payload.get("MessageType") == "SubscriptionConfirmation":
                                confirmed = True
                                progress("  subscription confirmed")
                                continue
                            row = _row_from_message(payload, dt.datetime.now(dt.UTC))
                            if row is None:
                                continue
                            buffer.append(row)
                            kept += 1
                            if len(buffer) >= _FLUSH_EVERY:
                                _flush(buffer, raw_dir)
                                progress(f"  {kept:,} kept / {total:,} seen")
                except TimeoutError:
                    break  # full sample duration elapsed
                # `async for` returned without a timeout: server closed cleanly.
                _flush(buffer, raw_dir)
                progress(f"  stream closed by server · {kept:,} kept · reconnecting")
                await asyncio.sleep(1)
        except (OSError, WebSocketException) as exc:
            _flush(buffer, raw_dir)
            # First connection, no confirmation, nothing received → almost
            # certainly a bad key or a malformed bounding box, not a transient
            # reset. Surface it instead of retrying to the deadline.
            if attempt == 1 and not confirmed and total == 0:
                raise RuntimeError(
                    "AISStream closed the connection with no data. Usual causes: an "
                    "invalid LOGJAM_AISSTREAM_API_KEY, or a malformed bounding box in "
                    "resources/ais_zones.yaml."
                ) from exc
            progress(f"  {type(exc).__name__} · {kept:,} kept · reconnecting")
            await asyncio.sleep(min(2 * attempt, 10))

    _flush(buffer, raw_dir)
    progress(f"done · {kept:,} messages kept from {total:,} received → {raw_dir}")
    return kept


def sample(
    minutes: float | None = None,
    *,
    progress: Callable[[str], None] = lambda _m: None,
) -> int:
    """Capture ~``minutes`` of AIS into ``settings.ais_raw_dir``. Returns messages kept.

    Blocking wrapper around the async client, for the CLI and cron.
    """
    mins = settings.ais_sample_minutes if minutes is None else minutes
    return asyncio.run(_run(mins, progress=progress))
