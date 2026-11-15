"""A-share corporate events: lock-up expiries, earnings preannouncements and preliminary results.

Offline: akshare is replaced by a fake module, the data directory is temporary,
and the clock is fixed at Saturday 2026-11-14 evening.
"""
from __future__ import annotations

import types

import pandas as pd
import pytest

from tradingagents.agents import tools
from tradingagents.dataflows import router
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.vendors.akshare import events, settings, store

pytestmark = pytest.mark.unit

TODAY = "2026-11-14"


def queue_em():
    return pd.DataFrame({
        "序号": [1, 2, 3], "解禁时间": ["2027-06-23", "2026-03-02", "2024-09-24"], "解禁股东数": [5, 2, 1],
        "解禁数量": [5.47e8, 1e7, 3.2e6], "实际解禁数量": [5.47e8, 1e7, 3.2e6], "未解禁数量": 0.0,
        "实际解禁数量市值": [6.0e10, 4.0e8, 6.3e8], "占总市值比例": [0.0639, 0.001, 0.0007],
        "占流通市值比例": [0.2735, 0.002, 0.0008], "解禁前一交易日收盘价": 100.0,
        "限售股类型": ["定向增发机构配售股份", "首发原股东限售股份", "股权激励限售股份"],
        "解禁前20日涨跌幅": 1.0, "解禁后20日涨跌幅": [None, 36.15, -10.86]})


def yjyg(date):
    if date == "20261231":
        return pd.DataFrame({
            "股票代码": ["688981", "688981", "600000"], "股票简称": "x", "预测指标": ["归属于上市公司股东的净利润", "营业收入", "x"],
            "业绩变动": ["预计2026年1-12月净利润盈利:14,000万元至16,000万元", "预计营业收入:3.8亿至4.2亿", "x"],
            "预测数值": 1.5e8, "业绩变动幅度": [26.64, 25.91, 1.0], "业绩变动原因": ["销售收入增长。", "销售收入增长。", "x"],
            "预告类型": ["略增", "略增", "预增"], "上年同期值": [1.18e8, 3.18e8, 1.0],
            "公告日期": ["2026-11-13", "2026-11-13", "2026-11-13"]})
    if date == "20260930":
        return pd.DataFrame({
            "股票代码": ["688981"], "股票简称": "x", "预测指标": ["归属于上市公司股东的净利润"], "业绩变动": ["预计扭亏"],
            "预测数值": 1.0, "业绩变动幅度": [None], "业绩变动原因": [None], "预告类型": ["扭亏"],
            "上年同期值": [-1e8], "公告日期": ["2026-11-20"]})   # announced after the run date
    raise TypeError("'NoneType' object is not subscriptable")    # Eastmoney: nothing announced yet


@pytest.fixture
def ak(tmp_path, monkeypatch):
    settings.set_data_dir(tmp_path / ".akshare_data")
    fake = types.SimpleNamespace(yjyg_calls=[])
    monkeypatch.setattr(store, "ak", lambda: fake)
    monkeypatch.setattr(store, "now_cst", lambda: pd.Timestamp(f"{TODAY} 20:00", tz=store.CST).to_pydatetime())
    monkeypatch.setattr(store, "is_intraday", lambda now=None: False)
    monkeypatch.setattr(store, "_CAL", pd.bdate_range("2020-01-01", "2027-12-31"))
    monkeypatch.setattr(events, "get_current_date", lambda: TODAY)
    fake.stock_restricted_release_queue_em = lambda symbol: queue_em()
    fake.stock_restricted_release_queue_sina = lambda symbol: pd.DataFrame(
        {"解禁日期": ["2027-06-23", "2026-03-02"], "公告日期": ["2026-06-25", "2025-02-28"]})
    fake.stock_yjyg_em = lambda date: fake.yjyg_calls.append(date) or yjyg(date)
    fake.stock_yjkb_em = lambda date: (pd.DataFrame({
        "股票代码": ["688981"], "股票简称": "x", "每股收益": [None], "营业收入-营业收入": [6.73e10],
        "营业收入-去年同期": 1, "营业收入-同比增长": [16.48], "营业收入-季度环比增长": 1, "净利润-净利润": [5.04e9],
        "净利润-去年同期": 1, "净利润-同比增长": [36.28], "净利润-季度环比增长": 1, "每股净资产": 1, "净资产收益率": [None],
        "所处行业": "x", "公告日期": ["2026-02-11"]}) if date == "20251231" else yjyg("none"))
    yield fake
    settings.set_data_dir(None)


def test_upcoming_expiries_need_an_announcement_by_the_run_date(ak):
    text = events.get_corporate_events("688981.SS", "2026-11-13")
    assert "| 2027-06-23 | 定向增发机构配售股份 | 5.47亿股 | 6.39% | 27.35% | 5 | 2026-06-25 |" in text
    assert "| 2026-03-02 | 首发原股东限售股份 |" in text, "a past expiry, as it happened"
    assert "36.15" not in text and "6.00亿元" not in text, "no after-expiry return, no upcoming market value"
    before = events.get_corporate_events("688981.SS", "2026-06-24")
    assert "2027-06-23" not in before and "without an announcement date" in before


def test_preannouncements_are_served_once_announced(ak):
    text = events.get_corporate_events("688981.SS", "2026-11-13")
    assert "| 年报 2026 | 2026-11-13 | 略增 | 归属于上市公司股东的净利润 |" in text
    assert "26.64%" in text and "1.18亿元" in text
    assert text.count("销售收入增长。") == 1 and "同上" in text, "one announcement's reason is written once"
    assert "扭亏" not in text, "announced on 11-20, after the run"
    assert "600000" not in text


def test_preliminary_results_and_a_missing_eps(ak):
    text = events.get_corporate_events("688981.SS", "2026-11-13")
    assert "| 年报 2025 | 2026-02-11 | 673.00亿元 | 16.48% | 50.40亿元 | 36.28% | — | — |" in text


def test_a_period_with_nothing_announced_is_empty_not_a_failure(ak):
    text = events.get_corporate_events("600519.SS", "2026-11-13")
    assert "could not be read" not in text
    assert "absence is normal" in text and "No restricted-share expiry" not in text


def test_period_tables_are_cached(ak):
    events.get_corporate_events("688981.SS", "2026-11-13")
    n = len(ak.yjyg_calls)
    events.get_corporate_events("600519.SS", "2026-11-13")
    assert len(ak.yjyg_calls) == n, "the whole-market tables are read once a day"


def test_an_unreachable_period_is_flagged(ak):
    def yg(date):
        if date == "20260630":
            raise ConnectionError("down")
        return yjyg(date)
    ak.stock_yjyg_em = yg
    text = events.get_corporate_events("688981.SS", "2026-11-13")
    assert "1 report period(s) could not be read" in text and "| 年报 2026 |" in text


def test_the_tool_serves_a_shares_only(ak):
    out = tools.get_corporate_events.func(ticker="AAPL", trade_date="2026-11-13")
    assert "China A-shares only" in out
    with run_config({}):
        out = tools.get_corporate_events.func(ticker="688981.SS", trade_date="2026-11-13")
    assert out.startswith("# A-share corporate events for 688981.SS")
    schema = tools.get_corporate_events.tool_call_schema.model_json_schema()["properties"]
    assert "ticker" not in schema and "trade_date" not in schema
    assert router.get_category_for_method("get_corporate_events") == "fundamental_data"
