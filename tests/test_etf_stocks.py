"""宽基ETF → 个股: a day's share changes × closes × index weights, summed per stock with each fund's part."""
import pandas as pd
import pytest

from web.server import etf_stocks

pytestmark = pytest.mark.unit

DAYS = ["2026-11-19", "2026-11-20"]


def _w(index, date, rows):
    return pd.DataFrame([{"index": index, "date": date, "code": c, "name": n, "weight": w} for c, n, w in rows])


W = pd.concat([
    _w("000016", "2026-10-30", [("600519", "贵州茅台", 60.0), ("601318", "中国平安", 40.0)]),
    _w("000300", "2026-10-30", [("600519", "贵州茅台", 10.0), ("300750", "宁德时代", 90.0)]),
    _w("000300", "2026-09-30", [("600519", "贵州茅台", 50.0), ("300750", "宁德时代", 50.0)]),
])
# 510050 (上证50) +10亿份 at 3元 = +30亿元; 510300 (沪深300) −5亿份 at 4元 = −20亿元; 510310 unchanged.
WIDE = pd.DataFrame({"510050": [100e8, 110e8], "510300": [50e8, 45e8], "510310": [20e8, 20e8]}, index=DAYS)
PX = pd.DataFrame({"510050": [2.9, 3.0], "510300": [4.1, 4.0], "510310": [4.0, None]}, index=DAYS)


def test_a_stock_sums_its_parts_from_each_fund():
    r = etf_stocks.implied("2026-11-20", wide=WIDE, px=PX, w=W)
    assert r["date"] == "2026-11-20" and r["total"] == 10.0 and r["count"] == 3 and r["note"] is None
    assert [(f["code"], f["amount"]) for f in r["funds"]] == [("510050", 30.0), ("510300", -20.0), ("510310", 0.0)]
    assert r["funds"][0]["weights_date"] == "2026-10-30", "the latest snapshot on or before the day"
    s = {x["code"]: x for x in r["stocks"]}
    assert s["600519"]["amount"] == 16.0 and s["600519"]["parts"] == [["510050", 18.0], ["510300", -2.0]]
    assert s["300750"]["amount"] == -18.0 and s["601318"]["amount"] == 12.0
    assert [x["code"] for x in r["stocks"]] == ["300750", "600519", "601318"], "by the size of the amount"
    assert len(etf_stocks.implied("2026-11-20", wide=WIDE, px=PX, w=W, top=1)["stocks"]) == 1


def test_an_earlier_day_uses_the_snapshot_then_and_a_missing_one_is_noted():
    early = WIDE.set_axis(["2026-09-29", "2026-09-30"])
    r = etf_stocks.implied(None, wide=early, px=PX.set_axis(early.index), w=W)
    assert r["date"] == "2026-09-30"
    assert {x["code"]: x["amount"] for x in r["stocks"]}["600519"] == 18.0 - 10.0, "沪深300 at 09-30's 50%"
    r = etf_stocks.implied("2026-11-20", wide=WIDE, px=PX, w=W[W["index"] != "000300"])
    assert "沪深300ETF华泰柏瑞" in r["note"] and [f["code"] for f in r["funds"]] == ["510050"]
    with pytest.raises(FileNotFoundError):
        etf_stocks.implied("2026-11-19", wide=WIDE, px=PX, w=W)      # no day before it


def test_weights_are_kept_and_asked_for_again_only_after_a_day(monkeypatch, tmp_path):
    monkeypatch.setattr(etf_stocks, "_path", lambda: tmp_path / "w.parquet")
    monkeypatch.setattr(etf_stocks, "_asked", {})
    asked = []

    def fetch(index):
        asked.append(index)
        if index == "399006":
            raise ConnectionError("down")
        return pd.DataFrame({"date": ["2026-10-30"], "code": ["600519"], "name": ["贵州茅台"], "weight": [1.0]})
    w = etf_stocks.weights(fetch)
    assert len(asked) == 10 and set(w["index"]) == {i for i, _ in etf_stocks.INDEX.values()} - {"399006"}
    assert len(etf_stocks.weights(fetch)) == len(w) and len(asked) == 10, "not again within the day"
    assert (tmp_path / "w.parquet").exists()


def test_every_fund_has_an_index():
    from web.server import etf_flow
    assert set(etf_stocks.INDEX) == set(etf_flow.NAMES)


def test_the_route(monkeypatch):
    from fastapi.testclient import TestClient

    from web.server import app as app_mod
    monkeypatch.setattr(etf_stocks, "implied", lambda day: {"date": day, "stocks": []})
    c = TestClient(app_mod.create_app() if hasattr(app_mod, "create_app") else app_mod.app)
    assert c.get("/api/etf/stocks?date=2026-11-20").json() == {"date": "2026-11-20", "stocks": []}
    assert c.get("/api/etf/stocks?date=bad").status_code == 422


def test_holdings_join_the_weights_with_the_quotes_heaviest_first():
    table = {"date": "2026-11-20", "rows": [
        {"code": "600519", "name": "贵州茅台", "price": 1485.75, "pct_chg": 1.75, "turnover": 0.54,
         "amount": 9.8e9, "pe_ttm": 22.6, "total_mv": 1.86e12, "industry": "食品饮料", "sub_industry": "白酒Ⅱ",
         "industry3": "白酒Ⅲ"},
    ]}
    roe = (pd.Series({"600519": 24.474, "300750": float("nan")}), "2026 三季报")
    r = etf_stocks.holdings("510300", w=W, table=table, roe=roe)
    assert (r["index_name"], r["weights_date"], r["date"], r["roe_label"], r["count"]) == (
        "沪深300", "2026-10-30", "2026-11-20", "2026 三季报", 2), "the index's latest snapshot"
    assert [x["code"] for x in r["rows"]] == ["300750", "600519"]
    assert r["rows"][1] == {"code": "600519", "name": "贵州茅台", "weight": 10.0, "industry": "食品饮料-白酒Ⅱ-白酒Ⅲ",
                            "price": 1485.75, "pct_chg": 1.75,
                            "turnover": 0.54, "amount": 9.8e9, "pe_ttm": 22.6, "total_mv": 1.86e12, "roe": 24.47}
    assert r["rows"][0]["name"] == "宁德时代" and r["rows"][0]["price"] is None and r["rows"][0]["roe"] is None
    assert r["rows"][0]["industry"] is None
    with pytest.raises(FileNotFoundError):
        etf_stocks.holdings("600519", w=W, table=table, roe=roe)
    with pytest.raises(FileNotFoundError):
        etf_stocks.holdings("588080", w=W, table=table, roe=roe)       # 科创50: no weights yet
