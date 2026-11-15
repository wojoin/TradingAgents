"""China A-shares through the analysts' tools: symbols, market routing, and the AKShare vendor.

Offline: akshare is replaced by a fake module and the data directory is temporary.
"""
from __future__ import annotations

import types

import pandas as pd
import pytest

from tradingagents.dataflows import markets, router
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError
from tradingagents.dataflows.symbols import a_share_code, normalize_symbol
from tradingagents.dataflows.vendors.akshare import (
    fundamentals,
    news,
    prices,
    settings,
    store,
)

pytestmark = pytest.mark.unit

TODAY = "2026-11-14"


@pytest.fixture
def ak(tmp_path, monkeypatch):
    """A fake akshare module, a temporary data dir, and a fixed clock (Saturday 2026-11-14)."""
    settings.set_data_dir(tmp_path / ".akshare_data")
    fake = types.SimpleNamespace()
    monkeypatch.setattr(store, "ak", lambda: fake)
    monkeypatch.setattr(store, "now_cst", lambda: pd.Timestamp(f"{TODAY} 20:00", tz=store.CST).to_pydatetime())
    monkeypatch.setattr(store, "is_intraday", lambda now=None: False)
    monkeypatch.setattr(fundamentals, "get_current_date", lambda: TODAY)
    monkeypatch.setattr(fundamentals, "is_historical", lambda d: bool(d) and str(d) < TODAY)
    yield fake
    settings.set_data_dir(None)


def bars(start="2026-06-01", end="2026-11-13", base=100.0):
    days = pd.bdate_range(start, end)
    close = base + pd.Series(range(len(days)), dtype=float) * 0.5
    return pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "open": close - 1, "high": close + 1,
                         "low": close - 2, "close": close, "volume": 1_000_000.0, "amount": close * 1e6,
                         "outstanding_share": 1e9, "turnover": 0.001})


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw, canonical", [
    ("600519", "600519.SS"), ("600519.SH", "600519.SS"), ("sh600519", "600519.SS"),
    ("000001", "000001.SZ"), ("SZ000001", "000001.SZ"), ("300750.sz", "300750.SZ"),
    ("688981", "688981.SS"), ("920001", "920001.BJ"), ("830799.BJ", "830799.BJ"),
    # not stocks: indices and funds stay Yahoo symbols
    ("000001.SS", "000001.SS"), ("000001.SH", "000001.SS"), ("399001.SZ", "399001.SZ"), ("510300", "510300"),
])
def test_a_share_symbols_normalize(raw, canonical):
    assert normalize_symbol(raw) == canonical


def test_a_share_code_requires_matching_exchange():
    assert a_share_code("600519.SS") == "600519"
    assert a_share_code("000001.SS") is None, "SSE Composite index, not the Shenzhen stock"
    assert a_share_code("SH000001") is None
    assert a_share_code("AAPL") is None and a_share_code("0700.HK") is None


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
@pytest.fixture
def vendors(monkeypatch):
    calls = []

    def fake(name, result=None, error=None):
        def f(symbol, *a, **k):
            calls.append((name, symbol))
            if error:
                raise error
            return result or f"{name}:{symbol}"
        return f
    table = {"yfinance": fake("yfinance"), "akshare": fake("akshare"), "alpha_vantage": fake("alpha_vantage")}
    monkeypatch.setitem(router.VENDOR_METHODS, "get_stock_data", table)
    return calls, table, fake


def test_a_share_takes_the_ashare_chain(vendors):
    calls, _, _ = vendors
    assert router.route_to_vendor("get_stock_data", "600519.SS", "2026-11-01", "2026-11-13") == "akshare:600519.SS"
    assert router.route_to_vendor("get_stock_data", "AAPL", "2026-11-01", "2026-11-13") == "yfinance:AAPL"


def test_a_share_falls_back_to_yahoo_when_akshare_cannot_answer(vendors, monkeypatch):
    calls, table, fake = vendors
    table["akshare"] = fake("akshare", error=VendorUnavailableError("rate limited"))
    assert router.route_to_vendor("get_stock_data", "600519.SS", "a", "b") == "yfinance:600519.SS"
    assert [c[0] for c in calls] == ["akshare", "yfinance"]


def test_akshare_never_serves_another_market(vendors):
    calls, _, _ = vendors
    with run_config({"data_vendors": {"core_stock_apis": "default"}}):
        router.route_to_vendor("get_stock_data", "AAPL", "a", "b")
        router.route_to_vendor("get_stock_data", "600519.SS", "a", "b")
    assert calls == [("yfinance", "AAPL"), ("akshare", "600519.SS")], "default chain: akshare leads A-shares only"
    with run_config({"data_vendors": {"core_stock_apis": "akshare"}}), pytest.raises(ValueError):
        router.route_to_vendor("get_stock_data", "AAPL", "a", "b")


def test_tool_level_ashare_override(vendors):
    calls, _, _ = vendors
    with run_config({"ashare_vendors": {"get_stock_data": "yfinance"}}):
        router.route_to_vendor("get_stock_data", "600519.SS", "a", "b")
    assert calls == [("yfinance", "600519.SS")]


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
def test_stock_data_forward_adjusted_from_sina(ak):
    seen = {}

    def daily(symbol, start_date, end_date, adjust):
        seen.update(symbol=symbol, adjust=adjust)
        return bars()
    ak.stock_zh_a_daily = daily
    text = prices.get_stock_data("600519.SS", "2026-11-09", "2026-11-13")
    assert seen == {"symbol": "sh600519", "adjust": "qfq"}
    assert "前复权" in text and "# Total records: 5" in text
    assert text.splitlines()[-1].startswith("2026-11-13,")
    assert "0.1" in text.splitlines()[-1], "turnover fraction shown in percent"


def test_eastmoney_is_the_second_source_and_volume_is_in_shares(ak):
    ak.stock_zh_a_daily = lambda **k: (_ for _ in ()).throw(ConnectionError("down"))
    b = bars()
    ak.stock_zh_a_hist = lambda **k: pd.DataFrame({
        "日期": b["date"], "开盘": b["open"], "收盘": b["close"], "最高": b["high"], "最低": b["low"],
        "成交量": 100.0, "成交额": b["amount"], "换手率": 0.5})
    df = prices.load_ohlcv("000001.SZ", "2026-11-13")
    assert df["Volume"].iat[-1] == 10_000 and list(df.columns) == prices.OHLCV


def test_price_errors_are_typed(ak):
    boom = lambda **k: (_ for _ in ()).throw(ConnectionError("down"))  # noqa: E731
    ak.stock_zh_a_daily = ak.stock_zh_a_hist = boom
    with pytest.raises(VendorUnavailableError):
        prices.load_ohlcv("600519.SS", "2026-11-13")
    with pytest.raises(NoMarketDataError, match="not a China A-share"):
        prices.load_ohlcv("AAPL", "2026-11-13")


def test_stale_bars_are_refused(ak):
    ak.stock_zh_a_daily = lambda **k: bars(end="2026-09-30")
    with pytest.raises(NoMarketDataError, match="stale|suspended"):
        prices.load_ohlcv("600519.SS", "2026-11-13")


def test_bars_after_the_analysis_date_are_never_served(ak):
    ak.stock_zh_a_daily = lambda **k: bars()
    df = prices.load_ohlcv("600519.SS", "2026-10-15")
    assert df["Date"].max() == pd.Timestamp("2026-10-15")
    text = prices.get_indicators("600519.SS", "rsi", "2026-10-15", 3)
    assert "2026-10-15:" in text and "2026-10-16" not in text


# ---------------------------------------------------------------------------
# Fundamentals
# ---------------------------------------------------------------------------
def report(rows):
    return pd.DataFrame([{"REPORT_DATE": f"{r} 00:00:00", "NOTICE_DATE": f"{n} 00:00:00", "REPORT_TYPE": t,
                          "REPORT_DATE_NAME": name, **vals} for r, n, t, name, vals in rows])


INCOME = report([
    ("2026-09-30", "2026-10-31", "三季报", "2026三季报", {"OPERATE_INCOME": 3e10, "OPERATE_COST": 1e10,
                                                    "PARENT_NETPROFIT": 1e10, "PARENT_NETPROFIT_YOY": 5.0}),
    ("2026-06-30", "2026-08-15", "中报", "2026中报", {"OPERATE_INCOME": 2e10, "OPERATE_COST": 7e9,
                                                "PARENT_NETPROFIT": 6e9, "PARENT_NETPROFIT_YOY": 4.0}),
    ("2025-12-31", "2026-04-17", "年报", "2025年报", {"OPERATE_INCOME": 4e10, "OPERATE_COST": 1.4e10,
                                                "PARENT_NETPROFIT": 1.3e10, "PARENT_NETPROFIT_YOY": 3.0}),
])
BALANCE = report([
    ("2026-09-30", "2026-10-31", "三季报", "2026三季报", {"TOTAL_ASSETS": 1e11, "TOTAL_LIABILITIES": 2e10,
                                                    "TOTAL_PARENT_EQUITY": 8e10}),
    ("2026-06-30", "2026-08-15", "中报", "2026中报", {"TOTAL_ASSETS": 9e10, "TOTAL_LIABILITIES": 2e10,
                                                "TOTAL_PARENT_EQUITY": 7e10}),
])
VALUE = pd.DataFrame({"数据日期": ["2026-08-31", "2026-11-13"], "当日收盘价": [1300.0, 1435.26],
                      "总市值": [1.6e12, 1.79e12], "流通市值": [1.6e12, 1.79e12], "PE(TTM)": [19.5, 21.8],
                      "PE(静)": [20.0, 21.8], "市净率": [6.0, 6.6], "PEG值": [float("nan"), 1.0],
                      "市现率": [15.0, 16.7], "市销率": [9.0, 10.3]})


@pytest.fixture
def fin(ak):
    ak.stock_profit_sheet_by_report_em = lambda symbol: INCOME
    ak.stock_balance_sheet_by_report_em = lambda symbol: BALANCE
    ak.stock_cash_flow_sheet_by_report_em = lambda symbol: INCOME.iloc[:0]
    ak.stock_value_em = lambda symbol: VALUE
    root = settings.data_dir()
    root.mkdir(parents=True)
    pd.DataFrame({"代码": ["600519"], "名称": ["贵州茅台"]}).to_pickle(root / "spot__20261113.pkl")
    pd.DataFrame({"证券代码": ["600519"], "证券名称": ["贵州茅台"], "行业代码": ["801120"]}).to_pickle(
        root / "sw_comp__2026W46.pkl")
    pd.DataFrame({"行业代码": ["801120.SI"], "行业名称": ["食品饮料"]}).to_pickle(root / "sw_first__2026W46.pkl")
    return ak


def test_statements_are_point_in_time_by_publication(fin):
    text = fundamentals.get_income_statement("600519.SS", "quarterly", "2026-09-01")
    assert "2026中报" in text and "2026三季报" not in text, "the Q3 report was published on 2026-10-31"
    assert "cumulative year to date" in text
    annual = fundamentals.get_income_statement("600519.SS", "annual", TODAY)
    assert "2025年报" in annual and "中报" not in annual.split("\n", 4)[-1]
    with pytest.raises(NoMarketDataError):
        fundamentals.get_balance_sheet("600519.SS", "quarterly", "2026-01-01")


def test_fundamentals_today_include_profile_and_industry(fin):
    text = fundamentals.get_fundamentals("600519.SS", TODAY)
    assert "贵州茅台" in text and "食品饮料" in text
    assert "PE (TTM): 21.80" in text and "PEG: 1.00" in text
    assert "Gross margin: 66.67%" in text and "ROE (year to date, not annualized): 12.50%" in text


def test_fundamentals_in_the_past_withhold_todays_facts(fin):
    text = fundamentals.get_fundamentals("600519.SS", "2026-09-01")
    assert "贵州茅台" not in text and "食品饮料" not in text and "withheld" in text
    assert "Valuation on 2026-08-31" in text and "PEG" not in text, "NaN multiples are left out"
    assert "2026中报" in text and "2026三季报" not in text


def test_fundamentals_survive_a_statement_outage(fin):
    fin.stock_profit_sheet_by_report_em = lambda symbol: (_ for _ in ()).throw(ConnectionError("down"))
    text = fundamentals.get_fundamentals("600519.SS", TODAY)
    assert "PE (TTM)" in text and "Unavailable right now" in text


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------
def test_news_filters_to_the_window_and_flags_unobserved_windows(ak, monkeypatch):
    ak.stock_news_em = lambda symbol: pd.DataFrame({
        "新闻标题": ["新", "旧"], "新闻内容": ["内容" * 300, "x"], "文章来源": ["财联社", "证券时报网"],
        "新闻链接": ["http://a", "http://b"], "发布时间": ["2026-11-13 10:00:00", "2026-11-10 09:00:00"]})
    text = news.get_news("600519.SS", "2026-11-12", "2026-11-14")
    assert "### 新 (source: 财联社" in text and "### 旧" not in text and "…" in text
    assert "only serves recent items" in news.get_news("600519.SS", "2025-01-01", "2025-01-07")


# ---------------------------------------------------------------------------
# Snapshot, identity and settlement
# ---------------------------------------------------------------------------
def test_snapshot_and_closes_use_akshare_bars(ak):
    ak.stock_zh_a_daily = lambda **k: bars()
    snap = markets.build_verified_market_snapshot("600519.SS", "2026-11-13", 3)
    assert "Latest trading row used: 2026-11-13" in snap and "| Volume | 1000000 |" in snap
    closes = markets.get_closes("600519.SS", "2026-11-10", "2026-11-13")
    assert list(closes.index.strftime("%Y-%m-%d")) == ["2026-11-10", "2026-11-11", "2026-11-12"]


def test_identity_comes_from_the_local_shenwan_tables(fin, monkeypatch):
    monkeypatch.setattr(markets, "yahoo_company_profile", lambda t: pytest.fail("asked Yahoo"))
    assert markets.get_company_profile("600519.SS") == {
        "longName": "贵州茅台", "exchange": "Shanghai Stock Exchange", "quoteType": "EQUITY", "sector": "食品饮料"}
