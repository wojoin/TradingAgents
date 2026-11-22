"""宽基ETF: the 19 broad-based ETFs' shares, their daily change and the 加仓指数.

Offline: the exchanges' fetchers are fakes, and the cache lives in a temporary folder.
"""
from __future__ import annotations

import pandas as pd
import pytest

from web.server import etf_flow

pytestmark = pytest.mark.unit

SH = [c for c, _, x in etf_flow.FUNDS if x == "SH"]
SZ = [c for c, _, x in etf_flow.FUNDS if x == "SZ"]

# Real shares (份) of the 19 funds from the exchanges, for checking against the charts this page
# reproduces: on 01-28 the summed change was about −329亿份 there, and the index 30.07 on 06-12 (+0.06).
REAL = {
    "2025-11-20": {"159629": 4017252600, "159845": 14742425600, "159901": 2061434900, "159915": 33035454900, "159919": 40473216600, "159952": 7532184900, "510050": 57031866800, "510180": 5682557700, "510230": 3435808000, "510300": 89383087700, "510310": 66363044000, "510330": 47234049800, "510500": 18530168600, "512100": 24995217600, "512500": 4103208800, "515800": 4224437200, "560010": 11175621700, "588050": 8369241300, "588080": 50818628100},
    "2025-12-31": {"159629": 4257252600, "159845": 15932425600, "159901": 2042534900, "159915": 31502454900, "159919": 40818816600, "159952": 7071484900, "510050": 56664666800, "510180": 5691057700, "510230": 3303808000, "510300": 88829587700, "510310": 65853644000, "510330": 47424849800, "510500": 19064568600, "512100": 25651217600, "512500": 4340008800, "515800": 4290437200, "560010": 11484621700, "588050": 8235241300, "588080": 51511628100},
    "2026-01-27": {"159629": 1489252600, "159845": 6248425600, "159901": 1924934900, "159915": 20690454900, "159919": 25216416600, "159952": 6940584900, "510050": 33157566800, "510180": 5591057700, "510230": 3322808000, "510300": 57532987700, "510310": 41232344000, "510330": 26060649800, "510500": 15058168600, "512100": 12753217600, "512500": 4566408800, "515800": 4276937200, "560010": 3543621700, "588050": 6543241300, "588080": 28525628100},
    "2026-01-28": {"159629": 1095252600, "159845": 4956425600, "159901": 1928434900, "159915": 19927454900, "159919": 22070916600, "159952": 6921884900, "510050": 28257966800, "510180": 5588057700, "510230": 3334808000, "510300": 51504787700, "510310": 34965644000, "510330": 20989149800, "510500": 14031768600, "512100": 11059217600, "512500": 3896008800, "515800": 4285937200, "560010": 2379621700, "588050": 6541241300, "588080": 28675628100},
    "2026-06-11": {"159629": 379252600, "159845": 1336425600, "159901": 945634900, "159915": 10689454900, "159919": 12495816600, "159952": 3564384900, "510050": 7738866800, "510180": 4836557700, "510230": 2199808000, "510300": 28730287700, "510310": 22319744000, "510330": 14380449800, "510500": 4350168600, "512100": 3299217600, "512500": 1584808800, "515800": 3147437200, "560010": 836621700, "588050": 4447241300, "588080": 19921628100},
    "2026-06-12": {"159629": 395252600, "159845": 1362425600, "159901": 952634900, "159915": 10642454900, "159919": 12413016600, "159952": 3484484900, "510050": 8164566800, "510180": 4825057700, "510230": 2174808000, "510300": 28624087700, "510310": 22206344000, "510330": 14265249800, "510500": 4453368600, "512100": 3507217600, "512500": 1612808800, "515800": 3147437200, "560010": 896621700, "588050": 4443241300, "588080": 19876628100},
}


def wide(rows: dict) -> pd.DataFrame:
    return pd.DataFrame.from_dict(rows, orient="index").sort_index()


# --- compute -------------------------------------------------------------------------------------

def test_compute_totals_changes_index_and_rates():
    w = wide({f"2026-01-0{i}": {"A": 1e8 * (10 + i), "B": 1e8 * 10} for i in range(1, 8)})
    out = etf_flow.compute(w, "2026-01-01").set_index("date")
    assert out.loc["2026-01-01", "total"] == 21.0                 # 亿份
    assert pd.isna(out.loc["2026-01-01", "change"])
    assert out.loc["2026-01-02", "change"] == 1.0
    assert out.loc["2026-01-01", "index"] == 100.0
    assert out.loc["2026-01-07", "index"] == pytest.approx(100 * 27 / 21)
    assert pd.isna(out.loc["2026-01-05", "rate5"])               # needs five days back
    assert out.loc["2026-01-06", "rate5"] == pytest.approx(100 * 5 / 21)
    assert out["rate20"].isna().all()


def test_compute_reproduces_the_charts_on_real_shares():
    out = etf_flow.compute(wide(REAL), etf_flow.BASE).set_index("date")
    # The video shows −329.48亿份 on 01-28 and 30.07 / +0.06 on 06-12; these 19 come within a few亿份 and 0.2.
    assert out.loc["2026-01-28", "change"] == pytest.approx(-322.64, abs=0.01)
    assert out.loc["2026-06-12", "index"] == pytest.approx(29.90, abs=0.01)
    assert round(out.loc["2026-06-12", "index_change"], 2) == 0.05
    assert pd.isna(out.loc["2025-11-20", "index_change"])


def test_compute_base_falls_back_to_the_last_day_before_it():
    w = wide(REAL)
    a = etf_flow.compute(w, "2026-01-01").set_index("date")        # a holiday: 2025-12-31 is used
    assert a.loc["2025-12-31", "index"] == 100.0
    assert a.attrs["base"] == "2025-12-31"
    with pytest.raises(ValueError):
        etf_flow.compute(w, "2025-01-01")
    with pytest.raises(ValueError, match="2026-03-02"):              # nothing within a week of it
        etf_flow.compute(w, "2026-03-02")


def test_a_day_that_times_out_is_retried_and_the_rest_still_come_in(cache):
    f = Fakes()
    calls: dict[str, int] = {}

    def flaky(day):
        calls[day] = calls.get(day, 0) + 1
        if day == "2026-01-27" and calls[day] < 2:
            raise TimeoutError("read timed out")
        if day == "2026-01-28":
            raise TimeoutError("read timed out")
        return f.sse(day)

    w, source, note = etf_flow.update(list(REAL), fetch_sse=flaky, fetch_szse=f.szse)
    assert calls["2026-01-27"] == 2 and calls["2026-01-28"] == 3
    assert list(w.index) == ["2025-11-20", "2025-12-31", "2026-01-27", "2026-06-11", "2026-06-12"]
    assert source == "stale" and "上交所" in note


# --- update: the cache top-up --------------------------------------------------------------------

class Fakes:
    """Both exchanges, serving ``REAL``; ``missing_sse`` days are not published yet."""

    def __init__(self, missing_sse=(), sse_error=False):
        self.sse_calls: list[str] = []
        self.szse_calls: list[tuple] = []
        self.missing_sse = set(missing_sse)
        self.sse_error = sse_error

    def sse(self, day):
        self.sse_calls.append(day)
        if self.sse_error:
            raise ConnectionError("上交所 down")
        if day in self.missing_sse or day not in REAL:
            return {}
        return {c: REAL[day][c] for c in SH}

    def szse(self, code, start, end):
        self.szse_calls.append((code, start, end))
        return {d: v[code] for d, v in REAL.items() if start <= d <= end}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(etf_flow, "_path", lambda: tmp_path / "etf_shares.parquet")
    monkeypatch.setattr(etf_flow, "_tried", {})
    monkeypatch.setattr(etf_flow, "_sleep", lambda s: None)
    return tmp_path / "etf_shares.parquet"


def test_update_fetches_everything_once(cache):
    f = Fakes()
    days = list(REAL)
    w, source, note = etf_flow.update(days, fetch_sse=f.sse, fetch_szse=f.szse)
    assert list(w.index) == days and w.shape[1] == 19
    assert source == "network" and note is None
    assert sorted(f.sse_calls) == days
    assert cache.exists()
    f2 = Fakes()
    w2, source2, _ = etf_flow.update(days, fetch_sse=f2.sse, fetch_szse=f2.szse)
    assert f2.sse_calls == [] and f2.szse_calls == [] and source2 == "cache"
    pd.testing.assert_frame_equal(w, w2)


def test_szse_is_fetched_a_month_at_a_time(cache):
    f = Fakes()
    etf_flow.update(list(REAL), fetch_sse=f.sse, fetch_szse=f.szse)
    spans = {(s, e) for _, s, e in f.szse_calls}
    assert spans == {("2025-11-01", "2025-11-30"), ("2025-12-01", "2025-12-31"), ("2026-01-01", "2026-01-31"), ("2026-06-01", "2026-06-30")}


def test_a_day_one_exchange_lacks_is_left_out_and_tried_again(cache, monkeypatch):
    days = list(REAL)
    f = Fakes(missing_sse={"2026-06-12"})
    w, _, note = etf_flow.update(days, fetch_sse=f.sse, fetch_szse=f.szse)
    assert "2026-06-12" not in w.index and not w.isna().any().any()
    assert "2026-06-12" in note
    f2 = Fakes()
    w2, _, _ = etf_flow.update(days, fetch_sse=f2.sse, fetch_szse=f2.szse)
    assert f2.sse_calls == []                                      # tried a moment ago: not again yet
    monkeypatch.setattr(etf_flow, "_tried", {})                    # half an hour on
    w3, _, _ = etf_flow.update(days, fetch_sse=f2.sse, fetch_szse=f2.szse)
    assert f2.sse_calls == ["2026-06-12"] and "2026-06-12" in w3.index


def test_an_exchange_that_fails_leaves_the_disk_and_says_so(cache):
    days = list(REAL)
    etf_flow.update(days[:3], fetch_sse=Fakes().sse, fetch_szse=Fakes().szse)
    w, source, note = etf_flow.update(days, fetch_sse=Fakes(sse_error=True).sse, fetch_szse=Fakes().szse)
    assert list(w.index) == days[:3]
    assert source == "stale" and "上交所" in note


# --- broad and the route -------------------------------------------------------------------------

def test_broad_shapes_the_page(cache, monkeypatch):
    monkeypatch.setattr(etf_flow, "_trade_days", lambda: list(REAL))
    f = Fakes()
    monkeypatch.setattr(etf_flow, "fetch_sse", f.sse)
    monkeypatch.setattr(etf_flow, "fetch_szse", f.szse)
    out = etf_flow.broad(None, "all")
    base_total = sum(REAL["2025-11-20"].values()) / 1e8
    assert out["base"] == "2025-11-20" and out["as_of"] == "2026-06-12"
    assert out["base_total"] == pytest.approx(base_total, abs=0.01)
    days = {d["date"]: d for d in out["days"]}
    assert days["2026-01-28"]["change"] == pytest.approx(-322.64, abs=0.01)
    assert days["2026-01-28"]["index_change"] == pytest.approx(100 * -322.64 / base_total, abs=0.01)
    assert days["2025-11-20"]["index_change"] is None
    assert days["2026-01-28"]["top"][0][0] == "510310"            # the day's biggest mover
    assert len(out["funds"]) == 19
    hs300 = next(x for x in out["funds"] if x["code"] == "510300")
    assert hs300["since_base"] == pytest.approx((28624087700 - 89383087700) / 1e8)
    assert sum(x["weight"] for x in out["funds"]) == pytest.approx(100, abs=0.01)
    with pytest.raises(ValueError):
        etf_flow.broad("2025-12-31", "5y")


def test_route(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from web.server.app import create_app
    from web.server.runs import RunManager
    seen = {}

    def fake(base, rng):
        seen.update(base=base, rng=rng)
        return {"base": base, "days": []}

    monkeypatch.setattr(etf_flow, "broad", fake)
    c = TestClient(create_app(RunManager(runner=lambda r, e: None), reports_root=tmp_path,
                              watchlist_path=tmp_path / "w.json"))
    r = c.get("/api/etf/broad?base=2026-01-05&range=6m")
    assert r.status_code == 200 and seen == {"base": "2026-01-05", "rng": "6m"}
    assert c.get("/api/etf/broad?base=2026-1-5").status_code == 422
