"""China macro indicators (china_*) from AKShare, and their routing beside FRED.

Offline: akshare is replaced by a fake module, the data directory is temporary,
and the clock is fixed at Saturday 2026-11-14 evening.
"""
from __future__ import annotations

import types

import pandas as pd
import pytest

from tradingagents.dataflows import router
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.vendors.akshare import macro, settings, store

pytestmark = pytest.mark.unit

TODAY = "2026-11-14"


def months(n=14, last="2026-10"):
    p = pd.period_range(end=last, periods=n, freq="M")
    return [f"{x.year}年{x.month:02d}月份" for x in p][::-1]   # Eastmoney serves newest first


@pytest.fixture
def ak(tmp_path, monkeypatch):
    settings.set_data_dir(tmp_path / ".akshare_data")
    fake = types.SimpleNamespace()
    monkeypatch.setattr(store, "ak", lambda: fake)
    monkeypatch.setattr(store, "now_cst", lambda: pd.Timestamp(f"{TODAY} 20:00", tz=store.CST).to_pydatetime())
    monkeypatch.setattr(store, "is_intraday", lambda now=None: False)
    monkeypatch.setattr(store, "_CAL", pd.bdate_range("2020-01-01", "2026-12-31"))
    monkeypatch.setattr(store.time, "sleep", lambda s: None)
    monkeypatch.setattr(macro, "get_current_date", lambda: TODAY)
    monkeypatch.setattr(macro, "is_historical", lambda d: bool(d) and str(d) < TODAY)
    m = months()
    fake.macro_china_cpi = lambda: pd.DataFrame({"月份": m, "全国-同比增长": [0.7 - i * 0.1 for i in range(len(m))],
                                                 "全国-环比增长": 0.1})
    yield fake
    settings.set_data_dir(None)


def test_a_live_run_reads_every_published_reading(ak):
    text = macro.get_macro_data("china_cpi", TODAY)
    assert "**Latest:** CPI 同比 % 0.70 (2026-10)" in text and "| 2026-10 | 0.70 | 0.10 |" in text


@pytest.mark.parametrize("as_of, latest", [
    ("2026-11-10", "2026-09"),     # October CPI is read from 11-11 in a past run
    ("2026-11-11", "2026-10"),
    ("2026-10-15", "2026-08"),     # September's is late: the October holiday
    ("2026-10-16", "2026-09"),
])
def test_a_past_run_reads_a_reading_only_after_its_release_day(ak, as_of, latest):
    assert f"({latest})" in macro.get_macro_data("china_cpi", as_of).split("**Latest:**")[1].splitlines()[0]


def test_a_feed_that_missed_releases_is_flagged_stale(ak):
    ak.macro_china_shrzgm = lambda: pd.DataFrame({"月份": ["202603", "202604"], "社会融资规模增量": [52240, 6245],
                                                 "其中-人民币贷款": [1, 2], "其中-企业债券": [3, 4]})
    text = macro.get_macro_data("china_tsf", TODAY)
    assert "Stale source: the latest period is 2026-04" in text
    assert "Stale" not in macro.get_macro_data("china_cpi", TODAY)


def test_quarterly_gdp_is_year_to_date(ak):
    ak.macro_china_gdp = lambda: pd.DataFrame({
        "季度": ["2026年第1-3季度", "2026年第1-2季度", "2026年第1季度"],
        "国内生产总值-同比增长": [4.6, 4.7, 4.8], "第二产业-同比增长": 3.8, "第三产业-同比增长": 5.2})
    text = macro.get_macro_data("china_gdp", "2026-10-19")
    assert "(2026Q2)" in text.split("**Latest:**")[1].splitlines()[0], "Q3 is read from 10-20"
    assert "(2026Q3)" in macro.get_macro_data("china_gdp", TODAY)


def test_unemployment_items_are_pivoted_and_trimmed(ak):
    ak.macro_china_urban_unemployment = lambda: pd.DataFrame({
        "date": ["202608", "202608", "202609", "202609"],
        "item": ["全国城镇调查失业率 ", "全国城镇外来户籍劳动力失业率 "] * 2, "value": ["5.3", "5.2", "5.2", "5.1"]})
    text = macro.get_macro_data("cn_unemployment", TODAY)
    assert "| 2026-09 | 5.20 | 5.10 |" in text and "25-59" not in text


def test_rrr_is_dated_by_announcement_and_never_shows_the_next_day_s_market(ak):
    ak.macro_china_reserve_requirement_ratio = lambda: pd.DataFrame({
        "公布时间": ["2025年05月07日", "2024年09月27日"], "生效时间": ["2025年05月15日", "2024年09月27日"],
        "大型金融机构-调整后": [9.0, 9.5], "中小金融机构-调整后": [6.0, 6.5], "大型金融机构-调整幅度": [-0.5, -0.5],
        "消息公布次日指数涨跌-上证": [0.3, 8.1]})
    text = macro.get_macro_data("china_rrr", "2025-05-06")
    assert "2025-05-07" not in text and "| 2024-09-27 | 9.50 |" in text
    assert "8.1" not in macro.get_macro_data("china_rrr", TODAY)


def test_overview_lists_each_series_and_names_the_failures(ak):
    ak.macro_china_pmi = lambda: pd.DataFrame({"月份": months(3), "制造业-指数": [49.3, 50.1, 49.8],
                                               "非制造业-指数": [49.7, 50.2, 50.0]})
    text = macro.get_macro_data("china_overview", TODAY)
    assert "| china_cpi | China CPI (NBS) | 2026-10 |" in text
    assert "| china_pmi |" in text and "50.10 (2026-09)" in text
    assert "china_lpr: unavailable" in text


def test_an_unknown_series_lists_the_names(ak):
    assert "china_overview, china_cpi" in macro.get_macro_data("china_bananas", TODAY)
    with pytest.raises(NoMarketDataError):
        macro.get_macro_data("cpi", TODAY)


def test_china_series_route_to_akshare_and_the_rest_to_fred(ak, monkeypatch):
    calls = []
    monkeypatch.setitem(router.VENDOR_METHODS["get_macro_indicators"], "fred",
                        lambda *a, **k: calls.append(("fred", a[0])) or "FRED")
    monkeypatch.setitem(router.VENDOR_METHODS["get_macro_indicators"], "akshare",
                        lambda *a, **k: calls.append(("akshare", a[0])) or "AK")
    with run_config({}):
        assert router.route_to_vendor("get_macro_indicators", "china_cpi", TODAY, None) == "AK"
        assert router.route_to_vendor("get_macro_indicators", "cpi", TODAY, None) == "FRED"
    with run_config({"data_vendors": {"macro_data": "default"}}):
        assert router.route_to_vendor("get_macro_indicators", "unemployment", TODAY, None) == "FRED"
    assert calls == [("akshare", "china_cpi"), ("fred", "cpi"), ("fred", "unemployment")]


def test_the_news_analyst_points_an_a_share_at_china_series(monkeypatch):
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    from tradingagents.agents.analysts import news_analyst

    seen = []

    class _LLM:
        def bind_tools(self, tools):
            return RunnableLambda(lambda prompt: seen.append(prompt.to_string()) or AIMessage(content="report"))

    for ticker, expect, absent in (("600519.SS", "china_overview", "'core_pce'"), ("NVDA", "'core_pce'", "china_")):
        seen.clear()
        news_analyst.create_news_analyst(_LLM())(
            {"company_of_interest": ticker, "trade_date": "2026-11-13", "messages": []})
        assert expect in seen[0] and absent not in seen[0]
