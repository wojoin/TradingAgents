"""宽基ETF: the 20 broad-based ETFs' shares, their daily change and the 加仓指数.

Offline: the exchanges' fetchers are fakes, and the cache lives in a temporary folder.
"""
from __future__ import annotations

import pandas as pd
import pytest

from web.server import etf_flow

pytestmark = pytest.mark.unit

SH = [c for c, _, x in etf_flow.FUNDS if x == "SH"]
SZ = [c for c, _, x in etf_flow.FUNDS if x == "SZ"]

# Real shares (份) of the 20 funds from the exchanges, for checking against the charts this page
# reproduces: on 01-28 the summed change was about −329亿份 there, and the index 30.07 on 06-12 (+0.06).
REAL = {
    "2025-11-20": {"159629": 4017252600, "159845": 14742425600, "159901": 2061434900, "159915": 33035454900, "159919": 40473216600, "159952": 7532184900, "510050": 57031866800, "510180": 5682557700, "510230": 3435808000, "510300": 89383087700, "510310": 66363044000, "510330": 47234049800, "510500": 18530168600, "512100": 24995217600, "512500": 4103208800, "515800": 4224437200, "560010": 11175621700, "588050": 8369241300, "588080": 50818628100, "159922": 4520676700},
    "2025-12-31": {"159629": 4257252600, "159845": 15932425600, "159901": 2042534900, "159915": 31502454900, "159919": 40818816600, "159952": 7071484900, "510050": 56664666800, "510180": 5691057700, "510230": 3303808000, "510300": 88829587700, "510310": 65853644000, "510330": 47424849800, "510500": 19064568600, "512100": 25651217600, "512500": 4340008800, "515800": 4290437200, "560010": 11484621700, "588050": 8235241300, "588080": 51511628100, "159922": 5213676700},
    "2026-01-27": {"159629": 1489252600, "159845": 6248425600, "159901": 1924934900, "159915": 20690454900, "159919": 25216416600, "159952": 6940584900, "510050": 33157566800, "510180": 5591057700, "510230": 3322808000, "510300": 57532987700, "510310": 41232344000, "510330": 26060649800, "510500": 15058168600, "512100": 12753217600, "512500": 4566408800, "515800": 4276937200, "560010": 3543621700, "588050": 6543241300, "588080": 28525628100, "159922": 5627676700},
    "2026-01-28": {"159629": 1095252600, "159845": 4956425600, "159901": 1928434900, "159915": 19927454900, "159919": 22070916600, "159952": 6921884900, "510050": 28257966800, "510180": 5588057700, "510230": 3334808000, "510300": 51504787700, "510310": 34965644000, "510330": 20989149800, "510500": 14031768600, "512100": 11059217600, "512500": 3896008800, "515800": 4285937200, "560010": 2379621700, "588050": 6541241300, "588080": 28675628100, "159922": 4944676700},
    "2026-06-11": {"159629": 379252600, "159845": 1336425600, "159901": 945634900, "159915": 10689454900, "159919": 12495816600, "159952": 3564384900, "510050": 7738866800, "510180": 4836557700, "510230": 2199808000, "510300": 28730287700, "510310": 22319744000, "510330": 14380449800, "510500": 4350168600, "512100": 3299217600, "512500": 1584808800, "515800": 3147437200, "560010": 836621700, "588050": 4447241300, "588080": 19921628100, "159922": 2153676700},
    "2026-06-12": {"159629": 395252600, "159845": 1362425600, "159901": 952634900, "159915": 10642454900, "159919": 12413016600, "159952": 3484484900, "510050": 8164566800, "510180": 4825057700, "510230": 2174808000, "510300": 28624087700, "510310": 22206344000, "510330": 14265249800, "510500": 4453368600, "512100": 3507217600, "512500": 1612808800, "515800": 3147437200, "560010": 896621700, "588050": 4443241300, "588080": 19876628100, "159922": 2201676700},
}


def wide(rows: dict) -> pd.DataFrame:
    return pd.DataFrame.from_dict(rows, orient="index").sort_index()


# --- compute -------------------------------------------------------------------------------------

def test_top_movers_stop_once_they_make_half_the_day():
    d = pd.Series({"A": 50.0, "B": 30.0, "C": 25.0, "D": 20.0, "E": 15.0, "F": 60.0, "G": -10.0, "H": 10.0})
    assert d.sum() == 200
    assert etf_flow.top_movers(d) == [["F", 60.0, 30.0], ["A", 50.0, 25.0]], "60 + 50 = 110 ≥ 100"
    assert [t[0] for t in etf_flow.top_movers(-d)] == ["F", "A"], "a day of redemptions likewise"
    flat = pd.Series({"A": 5.0, "B": -5.0, "C": 1.0, "D": -0.5})
    assert etf_flow.top_movers(flat) == [["A", 5.0, None], ["B", -5.0, None], ["C", 1.0, None]]


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
    assert out.loc["2026-01-28", "change"] == pytest.approx(-329.48, abs=0.01)     # the video: −329.48亿份
    assert round(out.loc["2026-06-12", "index"], 2) == 30.07                       # the video: 30.07
    assert round(out.loc["2026-06-12", "index_change"], 2) == 0.06                 # 较前日 +0.06
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


class Closes:
    """Sina's daily closes: 1.0 on every day of ``REAL`` (and the made-up days), 4.0 for 510300 from
    2026-06-12; a ``missing`` day is not there yet."""

    def __init__(self, missing=()):
        self.calls: list[str] = []
        self.missing = set(missing)

    def __call__(self, code):
        self.calls.append(code)
        days = sorted(REAL) + ["2026-06-15", "2026-06-16", "2026-06-17"]
        return {d: (4.0 if code == "510300" and d >= "2026-06-12" else 1.0) for d in days if d not in self.missing}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(etf_flow, "_path", lambda: tmp_path / "etf_shares.parquet")
    monkeypatch.setattr(etf_flow, "_tried", {})
    monkeypatch.setattr(etf_flow, "_sleep", lambda s: None)
    monkeypatch.setattr(etf_flow, "_closes_path", lambda: tmp_path / "etf_closes.parquet")
    monkeypatch.setattr(etf_flow, "fetch_close", Closes())
    return tmp_path / "etf_shares.parquet"


def test_update_fetches_everything_once(cache):
    f = Fakes()
    days = list(REAL)
    w, source, note = etf_flow.update(days, fetch_sse=f.sse, fetch_szse=f.szse)
    assert list(w.index) == days and w.shape[1] == 20
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
    assert days["2026-01-28"]["change"] == -329.48                       # exactly −329.475: half to even, as there
    assert days["2026-01-28"]["index_change"] == pytest.approx(100 * -329.48 / base_total, abs=0.01)
    assert days["2025-11-20"]["index_change"] is None
    top = days["2026-01-28"]["top"]
    assert top[0][0] == "510310"                                  # the day's biggest mover
    assert all(t[1] < 0 for t in top), "a day of redemptions: the funds redeemed"
    assert sum(t[2] for t in top) >= 50 and sum(t[2] for t in top[:-1]) < 50, "just enough for half"
    assert top[0][2] == pytest.approx(top[0][1] / -329.475 * 100, abs=0.01)
    assert len(out["funds"]) == 20
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


# --- the analysts' block -------------------------------------------------------------------------

@pytest.fixture
def report_data(monkeypatch, tmp_path):
    """The analysts' report over ``REAL`` (and two made-up later days), with no network."""
    from tradingagents.dataflows import broad_etf
    monkeypatch.setattr(etf_flow, "_closes_path", lambda: tmp_path / "etf_closes.parquet")
    monkeypatch.setattr(etf_flow, "fetch_close", Closes())
    monkeypatch.setattr(etf_flow, "_tried", {})
    rows = dict(REAL)
    rows["2026-06-15"] = {c: v * 1.01 for c, v in REAL["2026-06-12"].items()}
    rows["2026-06-16"] = {c: v * 1.02 for c, v in REAL["2026-06-12"].items()}
    rows["2026-06-17"] = {c: v * 0.9 for c, v in REAL["2026-06-12"].items()}
    days = sorted(rows)
    monkeypatch.setattr(etf_flow, "_trade_days", lambda: days)
    seen = {}

    def update(ds, **_):
        seen["days"] = ds
        return wide({d: rows[d] for d in ds}), "cache", None

    monkeypatch.setattr(etf_flow, "update", update)
    return broad_etf, seen


def test_the_report_reads_the_index_to_the_analysis_date_only(report_data):
    broad_etf, seen = report_data
    text = broad_etf.get_broad_etf_flow("2026-06-12")
    assert seen["days"][-1] == "2026-06-12"                       # nothing after the analysis date is asked for
    assert "2026-06-15" not in text and "2026-06-16" not in text
    assert "加仓指数 30.07" in text and "较前日 +0.06" in text       # base 2025-11-20: the video's numbers
    assert "在下轨 30 与上轨 70 之间" in text
    assert "2026-01-28 | -329.4" in text                            # the day-by-day table
    assert "基期 2025-11-20" in text


def test_the_report_names_the_zone_and_the_days_movers(report_data):
    broad_etf, _ = report_data
    text = broad_etf.get_broad_etf_flow("2026-06-16")
    assert "截至 2026-06-16" in text
    assert "在下轨 30 与上轨 70 之间" in text                         # 30.07 × 1.02 ≈ 30.67
    assert "沪深300ETF华泰柏瑞" in text                               # the biggest mover that day


def test_the_report_below_the_lower_band_says_cut_positions(report_data):
    broad_etf, _ = report_data
    assert "在下轨 30 之下：需要减仓了" in broad_etf.get_broad_etf_flow("2026-06-17")    # 30.07 × 0.9 ≈ 27.06


def test_the_report_before_the_base_day_says_it_is_unavailable(report_data):
    broad_etf, _ = report_data
    assert "unavailable" in broad_etf.get_broad_etf_flow("2025-11-19")


# --- size: shares × the day's close ---------------------------------------------------------------

def test_sizes_are_the_days_shares_times_its_close_and_their_order_moves(cache):
    w = wide(REAL)
    a = etf_flow.sizes("2026-06-11", w)
    b = etf_flow.sizes("2026-06-12", w)
    assert a["510300"] == pytest.approx(28730287700 / 1e8)               # close 1.0
    assert b["510300"] == pytest.approx(4 * 28624087700 / 1e8)           # close 4.0 that day
    assert list(a.index[:2]) == ["510300", "510310"] and a.is_monotonic_decreasing
    assert b.index[0] == "510300" and b.iloc[0] > 4 * b.iloc[1]          # each day ranked on its own


def test_closes_are_kept_and_only_a_missing_day_is_asked_for_again(cache, monkeypatch):
    w = wide(REAL)
    etf_flow.sizes("2026-06-12", w)
    first = etf_flow.fetch_close
    assert sorted(first.calls) == sorted(etf_flow.NAMES)                  # one request per fund
    again = Closes()
    monkeypatch.setattr(etf_flow, "fetch_close", again)
    etf_flow.sizes("2026-06-12", w)
    assert again.calls == []                                              # on disk


def test_a_day_without_a_close_uses_the_last_close_before_it(cache, monkeypatch):
    monkeypatch.setattr(etf_flow, "fetch_close", Closes(missing={"2026-06-12"}))
    s = etf_flow.sizes("2026-06-12", wide(REAL))
    assert s["510300"] == pytest.approx(28624087700 / 1e8)               # the 06-11 close, 1.0


def test_broad_lists_the_funds_by_the_days_size(cache, monkeypatch):
    monkeypatch.setattr(etf_flow, "_trade_days", lambda: list(REAL))
    f = Fakes()
    monkeypatch.setattr(etf_flow, "fetch_sse", f.sse)
    monkeypatch.setattr(etf_flow, "fetch_szse", f.szse)
    out = etf_flow.broad(None, "all")
    sizes = [x["size"] for x in out["funds"]]
    assert sizes == sorted(sizes, reverse=True) and out["funds"][0]["code"] == "510300"
    assert out["funds"][0]["size"] == pytest.approx(4 * 28624087700 / 1e8, abs=0.01)


def test_broad_without_closes_still_serves_the_index(cache, monkeypatch):
    monkeypatch.setattr(etf_flow, "_trade_days", lambda: list(REAL))
    f = Fakes()
    monkeypatch.setattr(etf_flow, "fetch_sse", f.sse)
    monkeypatch.setattr(etf_flow, "fetch_szse", f.szse)

    def down(code):
        raise ConnectionError("新浪 down")

    monkeypatch.setattr(etf_flow, "fetch_close", down)
    out = etf_flow.broad(None, "all")
    assert all(x["size"] is None for x in out["funds"])
    assert "规模" in out["note"]
    assert {d["date"]: d for d in out["days"]}["2026-06-12"]["index"] == pytest.approx(30.07, abs=0.01)


def test_the_report_lists_the_funds_by_the_days_size(report_data):
    broad_etf, _ = report_data
    text = broad_etf.get_broad_etf_flow("2026-06-12")
    assert "按 2026-06-12 规模排序" in text
    table = text[text.index("按 2026-06-12 规模排序"):]
    assert table.index("沪深300ETF华泰柏瑞") < table.index("沪深300ETF易方达")


def test_numbers_round_half_to_even_like_the_reference():
    # The reference shows −329.48 and +196.98 where the shares give exactly −329.475 and +196.985.
    assert etf_flow.round_half_even(-329.475) == -329.48
    assert etf_flow.round_half_even(196.985) == 196.98
    assert etf_flow.round_half_even(196.98500001) == 196.99
    assert etf_flow.round_half_even(30.066403) == 30.07
    assert etf_flow.round_half_even(None) is None and etf_flow.round_half_even(float("nan")) is None
    assert etf_flow.round_half_even(1.23456, 4) == 1.2346


def test_shares_are_kept_as_whole_units(cache):
    f = Fakes()
    real_szse = f.szse
    f.szse = lambda code, s, e: {d: v + 0.0000076 for d, v in real_szse(code, s, e).items()}   # float noise
    w, _, _ = etf_flow.update(list(REAL), fetch_sse=f.sse, fetch_szse=f.szse)
    assert (w % 1 == 0).all().all()
