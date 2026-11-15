"""A-share insider trades: 董监高 from the exchanges and major shareholders from THS.

Offline: akshare is replaced by a fake module, the data directory is temporary,
and the clock is fixed at Saturday 2026-11-14 evening.
"""
from __future__ import annotations

import types

import pandas as pd
import pytest

from tradingagents.dataflows import router
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError
from tradingagents.dataflows.vendors.akshare import insiders, settings, store

pytestmark = pytest.mark.unit

TODAY = "2026-11-14"


@pytest.fixture
def ak(tmp_path, monkeypatch):
    settings.set_data_dir(tmp_path / ".akshare_data")
    fake = types.SimpleNamespace()
    monkeypatch.setattr(store, "ak", lambda: fake)
    monkeypatch.setattr(store, "now_cst", lambda: pd.Timestamp(f"{TODAY} 20:00", tz=store.CST).to_pydatetime())
    monkeypatch.setattr(store, "is_intraday", lambda now=None: False)
    monkeypatch.setattr(store, "_CAL", pd.bdate_range("2020-01-01", "2026-12-31"))
    monkeypatch.setattr(insiders, "get_current_date", lambda: TODAY)
    fake.stock_shareholder_change_ths = lambda symbol: pd.DataFrame()
    yield fake
    settings.set_data_dir(None)


def _boom(*a, **k):
    raise ConnectionError("down")


@pytest.mark.parametrize("raw, value", [
    ("增持4.16万", 41_600), ("减持40.43万", -404_300), ("5.82亿", 5.82e8), ("增持700.00", 700), (12.5, 12.5),
])
def test_cn_numbers(raw, value):
    assert insiders.cn_number(raw) == pytest.approx(value)
    assert pd.isna(insiders.cn_number("未披露"))


def sse_rows():
    return pd.DataFrame({
        "公司代码": "600519", "公司名称": "贵州茅台", "姓名": ["甲", "乙"], "职务": ["董事", "高级管理人员"],
        "本次变动前持股数": [1000, 0], "变动数": [-500, 200], "本次变动平均价格": [1500.0, 1400.0],
        "变动后持股数": [500, 200], "变动原因": "二级市场买卖",
        "变动日期": ["2026-11-10", "2026-06-01"], "填报日期": ["2026-11-16", "2026-06-02"]})


def test_sse_trades_are_dated_by_filing(ak):
    ak.stock_share_hold_change_sse = lambda symbol: sse_rows()
    text = insiders.get_insider_transactions("600519.SS", "2026-11-13")
    assert "Source: 上交所披露" in text
    assert "| 2026-06-02 | 2026-06-01 | 乙 |" in text
    assert "甲" not in text, "filed on 11-16, after the run date"
    assert "近12个月: 增持 1 笔 +200股, 减持 0 笔" in text and "+28.0万元" in text
    assert "(估)" not in text.split("Notes:")[0]


def test_szse_trades_are_public_two_trading_days_later(ak):
    ak.stock_share_hold_change_szse = lambda symbol: pd.DataFrame({
        "证券代码": ["300750", "000001"], "证券简称": ["宁德时代", "平安银行"], "董监高姓名": ["黄世霖", "x"],
        "变动日期": ["2026-11-12", "2026-11-12"], "变动股份数量": [-30.45, 1.0], "成交均价": [400.0, 10.0],
        "变动原因": "大宗交易", "变动比例": 0.1, "当日结存股数": [25890.07, 1.0], "股份变动人姓名": ["黄世霖", "x"],
        "职务": ["董事、高管", "董事"], "变动人与董监高的关系": ["本人", "本人"]})
    # Thursday 11-12 + 2 trading days = Monday 11-16
    assert "No trade disclosed" in insiders.get_insider_transactions("300750.SZ", "2026-11-13")
    text = insiders.get_insider_transactions("300750.SZ", "2026-11-16")
    assert "| 2026-11-16 (估) | 2026-11-12 | 黄世霖 | 董事、高管 | -30.45万股 |" in text
    assert "2.59亿股" in text and "平安" not in text


def test_bse_signs_the_change_from_the_holding(ak):
    ak.stock_share_hold_change_bse = lambda symbol: pd.DataFrame({
        "代码": "430489", "简称": "佳先股份", "姓名": ["李平"], "职务": ["高级管理人员"], "变动日期": ["2026-10-08"],
        "变动股数": [2.0], "变动前持股数": [25.0], "变动后持股数": [23.0], "变动均价": [4.6], "变动原因": "竞价交易"})
    text = insiders.get_insider_transactions("430489.BJ", "2026-11-13")
    assert "-2.00万股" in text and "减持 1 笔" in text


def test_ths_covers_an_unreachable_exchange(ak):
    ak.stock_share_hold_change_sse = _boom
    ak.stock_management_change_ths = lambda symbol: pd.DataFrame({
        "变动日期": ["2026-09-01"], "变动人": ["万波"], "与公司高管关系": ["高级管理人员"], "变动数量": ["减持700.00"],
        "交易均价": ["725.92"], "剩余股数": ["0.00"], "股份变动途径": ["二级市场买卖"]})
    text = insiders.get_insider_transactions("600519.SS", "2026-11-13")
    assert "同花顺 (THS; 上交所披露 unreachable)" in text and "-700股" in text


def test_a_transfer_s_buyers_are_not_counted_as_increases(ak):
    ak.stock_share_hold_change_sse = lambda symbol: pd.DataFrame(columns=sse_rows().columns)
    period = "2026.04.23-2026.04.23"
    ak.stock_shareholder_change_ths = lambda symbol: pd.DataFrame({
        "公告日期": ["2026-04-24"] * 3 + ["2026-08-01"],
        "变动股东": ["大股东A", "基金B", "基金C", "大股东A"],
        "变动数量": ["减持5800.00万", "增持5000.00万", "增持800.00万", "增持100.00万"],
        "交易均价": ["410.34", "410.34", "410.34", "未披露"],
        "剩余股份总数": ["2.26亿", "5000.00万", "800.00万", "2.27亿"],
        "变动期间": [period] * 3 + ["2026.07.01-2026.07.31"], "变动途径": ["询价转让"] * 3 + ["二级市场"]})
    text = insiders.get_insider_transactions("600519.SS", "2026-11-13")
    assert "近12个月: 增持 1 笔 +100.00万股, 减持 1 笔 -5800.00万股" in text
    assert "另有转让受让方 2 家受让 +5800.00万股, 不计入增持" in text
    assert "受让方 2 家 (基金B、基金C)" in text
    assert "1 笔未披露价格" in text


def test_shareholder_announcements_after_the_run_are_withheld(ak):
    ak.stock_share_hold_change_sse = lambda symbol: pd.DataFrame(columns=sse_rows().columns)
    ak.stock_shareholder_change_ths = lambda symbol: pd.DataFrame({
        "公告日期": ["2026-11-20"], "变动股东": ["大股东A"], "变动数量": ["减持1.00万"], "交易均价": ["1.0"],
        "剩余股份总数": ["1.00亿"], "变动期间": ["2026.11.10-2026.11.12"], "变动途径": ["二级市场"]})
    assert "大股东A" not in insiders.get_insider_transactions("600519.SS", "2026-11-13")


def test_errors_are_typed(ak):
    ak.stock_share_hold_change_sse = ak.stock_management_change_ths = ak.stock_shareholder_change_ths = _boom
    with pytest.raises(VendorUnavailableError):
        insiders.get_insider_transactions("600519.SS", "2026-11-13")
    with pytest.raises(NoMarketDataError):
        insiders.get_insider_transactions("AAPL", "2026-11-13")


def test_an_a_share_routes_to_akshare_only(ak, monkeypatch):
    monkeypatch.setitem(router.VENDOR_METHODS["get_insider_transactions"], "yfinance",
                        lambda *a, **k: pytest.fail("Yahoo has no A-share insider data"))
    ak.stock_share_hold_change_sse = ak.stock_management_change_ths = ak.stock_shareholder_change_ths = _boom
    with run_config({}):
        out = router.route_to_vendor("get_insider_transactions", "600519.SS", "2026-11-13")
    assert out.startswith("DATA_UNAVAILABLE")
