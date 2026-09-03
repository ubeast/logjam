"""GDELT adapter tests - DOC 2.0 responses are mocked, no network."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx

from logjam.config import settings
from logjam.ingest.gdelt import GdeltUnavailable, _daily_tone, _daily_volume, fetch_gdelt
from logjam.ingest.portwatch import TIDY_COLUMNS


def test_daily_volume_rolls_subhourly_points_to_permille_share() -> None:
    rows = [
        {"date": "20260810T000000Z", "value": 30, "norm": 3000},
        {"date": "20260810T010000Z", "value": 30, "norm": 1000},  # same day
        {"date": "20260811T000000Z", "value": 5, "norm": 5000},
    ]
    daily = _daily_volume(rows)
    assert daily[dt.date(2026, 8, 10)] == pytest.approx(1000 * 60 / 4000)  # 15.0 per-mille
    assert daily[dt.date(2026, 8, 11)] == pytest.approx(1.0)


def test_daily_tone_is_a_daily_mean_and_skips_nulls() -> None:
    rows = [
        {"date": "20260810T000000Z", "value": -2.0},
        {"date": "20260810T120000Z", "value": -4.0},
        {"date": "20260810T180000Z", "value": None},
        {"date": "20260811T000000Z", "value": 1.5},
    ]
    daily = _daily_tone(rows)
    assert daily[dt.date(2026, 8, 10)] == pytest.approx(-3.0)
    assert daily[dt.date(2026, 8, 11)] == pytest.approx(1.5)


def _timeline(series: str, points: list[dict]) -> dict:
    return {"timeline": [{"series": series, "data": points}]}


@respx.mock
def test_fetch_gdelt_returns_tidy_chokepoint_rows() -> None:
    today = dt.date.today()
    d = (today - dt.timedelta(days=2)).strftime("%Y%m%d")

    def _respond(request: httpx.Request) -> httpx.Response:
        mode = request.url.params["mode"]
        if mode == "timelinevolraw":
            return httpx.Response(200, json=_timeline(
                "Article Count", [{"date": f"{d}T000000Z", "value": 40, "norm": 4000}]
            ))
        return httpx.Response(200, json=_timeline(
            "Average Tone", [{"date": f"{d}T000000Z", "value": -6.5}]
        ))

    respx.get(settings.gdelt_doc_url).mock(side_effect=_respond)

    df = fetch_gdelt(since=today - dt.timedelta(days=5))

    assert list(df.columns) == TIDY_COLUMNS
    assert (df["entity_type"] == "chokepoint").all()
    assert set(df["metric"]) == {"gdelt_volume", "gdelt_tone"}
    assert df["country"].isna().all()

    hormuz = df[(df.entity_id == "chokepoint6") & (df.metric == "gdelt_volume")]
    assert not hormuz.empty
    assert hormuz["value"].iloc[0] == pytest.approx(10.0)  # 1000 * 40/4000
    assert "Hormuz" in hormuz["entity_name"].iloc[0]


@respx.mock
def test_fetch_gdelt_raises_only_when_every_call_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gdelt_request_pause_s", 0.0)  # no real sleeping
    monkeypatch.setattr("logjam.ingest.gdelt._queries", lambda: {"chokepoint6": '"Hormuz"'})
    respx.get(settings.gdelt_doc_url).mock(return_value=httpx.Response(429))
    with pytest.raises(GdeltUnavailable):
        fetch_gdelt(since=dt.date.today() - dt.timedelta(days=3))


@respx.mock
def test_fetch_gdelt_returns_partial_when_some_calls_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gdelt_request_pause_s", 0.0)
    monkeypatch.setattr(
        "logjam.ingest.gdelt._queries",
        lambda: {"chokepoint6": '"Hormuz"', "chokepoint1": '"Suez"'},
    )
    d = (dt.date.today() - dt.timedelta(days=2)).strftime("%Y%m%d")

    def _respond(request: httpx.Request) -> httpx.Response:
        if "Hormuz" in request.url.params["query"]:
            return httpx.Response(429)  # this chokepoint fails every retry
        if request.url.params["mode"] == "timelinevolraw":
            return httpx.Response(200, json=_timeline(
                "Article Count", [{"date": f"{d}T000000Z", "value": 10, "norm": 5000}]))
        return httpx.Response(200, json=_timeline(
            "Average Tone", [{"date": f"{d}T000000Z", "value": -1.0}]))

    respx.get(settings.gdelt_doc_url).mock(side_effect=_respond)
    df = fetch_gdelt(since=dt.date.today() - dt.timedelta(days=5))
    assert set(df["entity_id"]) == {"chokepoint1"}  # only the one that succeeded


def test_fetch_gdelt_empty_when_since_after_window() -> None:
    # since in the future -> clamped range collapses -> empty frame, no HTTP.
    df = fetch_gdelt(since=dt.date.today() + dt.timedelta(days=5))
    assert df.empty
    assert list(df.columns) == TIDY_COLUMNS
