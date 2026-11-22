"""A-share sentiment blocks (资金情绪 / 市场情绪 / 人气) and the sentiment analyst's A-share path.

Offline: akshare is replaced by a fake module, the data directory is temporary,
and the clock is fixed at Saturday 2026-11-14 evening.
"""
from __future__ import annotations

import types

import pandas as pd
import pytest

from tradingagents.dataflows.vendors.akshare import sentiment, settings, store

pytestmark = pytest.mark.unit

TODAY = "2026-11-14"
DAYS = pd.bdate_range("2026-06-01", "2026-11-13")


@pytest.fixture
def ak(tmp_path, monkeypatch):
    settings.set_data_dir(tmp_path / ".akshare_data")
    fake = types.SimpleNamespace()
    monkeypatch.setattr(store, "ak", lambda: fake)
    monkeypatch.setattr(store, "now_cst", lambda: pd.Timestamp(f"{TODAY} 20:00", tz=store.CST).to_pydatetime())
    monkeypatch.setattr(store, "is_intraday", lambda now=None: False)
    monkeypatch.setattr(store, "_CAL", pd.bdate_range("2026-01-01", "2026-12-31"))
    monkeypatch.setattr(sentiment.time, "sleep", lambda s: None)
    yield fake
    settings.set_data_dir(None)


def _boom(*a, **k):
    raise ConnectionError("down")


# ---------------------------------------------------------------------------
# 资金情绪
# ---------------------------------------------------------------------------
def fund_flow(days=DAYS[-30:]):
    n = len(days)
    main = [1e8 if i % 2 else -0.5e8 for i in range(n)]
    return pd.DataFrame({
        "日期": days.strftime("%Y-%m-%d"), "收盘价": 100.0, "涨跌幅": 1.0,
        "主力净流入-净额": main, "主力净流入-净占比": 2.0,
        "超大单净流入-净额": 0.4e8, "超大单净流入-净占比": 1.0,
        "大单净流入-净额": 0.1e8, "大单净流入-净占比": 0.5,
        "中单净流入-净额": 0.0, "中单净流入-净占比": 0.0,
        "小单净流入-净额": -0.2e8, "小单净流入-净占比": -1.0,
    })


def test_fund_flow_stops_at_the_trade_date(ak):
    seen = {}
    ak.stock_individual_fund_flow = lambda stock, market: seen.update(stock=stock, market=market) or fund_flow()
    text = sentiment._fund_flow("600519", "2026-11-10")
    assert seen == {"stock": "600519", "market": "sh"}
    assert "| 2026-11-10 |" in text and "2026-11-11" not in text
    assert "主力净流入合计" in text and "20日" in text


def test_fund_flow_before_the_feed_starts_is_unobserved(ak):
    ak.stock_individual_fund_flow = lambda **k: fund_flow()
    text = sentiment._fund_flow("600519", "2026-01-05")
    assert "unobserved" in text and "not an absence" in text


def _margin_table(code_col, codes, balance=1e10):
    return pd.DataFrame({code_col: codes, "融资余额": balance, "融资买入额": 2e8, "融券余量": 1e5, "融券卖出量": 1e4})


def test_margin_is_read_through_the_day_before_and_from_the_right_exchange(ak):
    asked = []

    def szse(date):
        asked.append(date)
        return _margin_table("证券代码", ["000001", "000002"], balance=1e10 + int(date[-2:]) * 1e7)
    ak.stock_margin_detail_szse = szse
    text = sentiment._margin("000001", "2026-11-13")
    assert "20261113" not in asked and asked[-1] == "20261112"
    assert len(asked) == sentiment.MARGIN_DAYS
    assert "| 2026-11-12 |" in text and "融资余额 " in text
    assert (store.root() / "sentiment" / "margin_SZ" / "20261112.pkl").exists(), "closed days cached for good"


def test_margin_flags_a_non_target(ak):
    ak.stock_margin_detail_sse = lambda date: _margin_table("标的证券代码", ["600000"])
    assert "not in the SSE margin-trading list" in sentiment._margin("600519", "2026-11-13")


def test_margin_flags_a_missing_day_after_a_retry(ak):
    calls = []

    def sse(date):
        calls.append(date)
        if date == "20261112":
            raise ConnectionError("down")
        return _margin_table("标的证券代码", ["600519"])
    ak.stock_margin_detail_sse = sse
    text = sentiment._margin("600519", "2026-11-14")
    assert "Missing days" in text and "2026-11-12" in text.split("Missing days")[1]
    assert calls.count("20261112") == 2, "an exchange's dropped request is retried once"


def test_northbound_after_the_disclosure_ended_is_unobserved(ak):
    ak.stock_hsgt_individual_em = lambda symbol: pd.DataFrame({
        "持股日期": ["2024-08-15", "2024-08-16"], "持股数量": [8e7, 8.1e7], "持股数量占A股百分比": [6.5, 6.55],
        "今日增持股数": [1e5, 1e6], "今日增持资金": [1e8, 1e9]})
    text = sentiment._northbound("600519", "2026-11-13")
    assert "stop at 2024-08-16" in text and "unobserved" in text
    recent = sentiment._northbound("600519", "2024-08-16")
    assert "| 2024-08-16 |" in recent and "增持资金合计" in recent


def test_lhb_classifies_seats_and_never_double_counts(ak):
    ak.stock_lhb_stock_detail_date_em = lambda symbol: pd.DataFrame(
        {"序号": [1, 2], "股票代码": "000026", "交易日": ["2026-11-11", "2026-01-05"]})
    seats = pd.DataFrame({
        "交易营业部名称": ["机构专用", "深股通专用", "某证券西安营业部", "机构专用"],
        "买入金额": [5e7, 1e8, 9e7, 1e7], "卖出金额": [1e7, 9e7, 1e7, 3e7], "类型": "连续三个交易日内涨幅偏离值累计达到20%"})
    ak.stock_lhb_stock_detail_em = lambda symbol, date, flag: seats   # both sides list the same seats
    text = sentiment._lhb("000026", "2026-11-13")
    assert "1 listing day(s)" in text and "**2026-11-11**" in text
    assert "机构专用: 2 席, 净买入 +0.20亿" in text
    assert "北向专用席位: 1 席" in text and "某证券西安营业部 +0.80亿" in text
    assert "上榜席位净买入合计 +1.10亿" in text


def test_no_lhb_listing_is_said_to_be_normal(ak):
    ak.stock_lhb_stock_detail_date_em = lambda symbol: pd.DataFrame({"交易日": ["2013-01-28"]})
    assert "normal state, not a signal" in sentiment._lhb("600519", "2026-11-13")


def test_fund_block_survives_a_source_outage(ak):
    ak.stock_individual_fund_flow = _boom
    ak.stock_margin_detail_sse = lambda date: _margin_table("标的证券代码", ["600519"])
    ak.stock_hsgt_individual_em = _boom
    ak.stock_lhb_stock_detail_date_em = lambda symbol: pd.DataFrame({"交易日": []})
    text = sentiment.get_fund_sentiment("600519.SS", "2026-11-13")
    assert "### 个股资金流" in text and "<fund flow unavailable: VendorUnavailableError: Eastmoney" in text
    assert "同花顺 fallback" in text
    assert "| 2026-11-12 |" in text, "margin still served"
    assert "<northbound holdings unavailable" in text


# ---------------------------------------------------------------------------
# 市场情绪
# ---------------------------------------------------------------------------
def test_market_sentiment_computes_broken_rate_height_and_premium(ak):
    def zt(date):
        if date < "20261111":
            raise ValueError("炸板股池只能获取最近 30 个交易日的数据")
        return pd.DataFrame({"代码": ["000026", "600001", "600002", "600003"], "名称": ["飞亚达", "甲", "乙", "丙"],
                             "连板数": [3, 1, 2, 1], "所属行业": ["钟表", "汽车", "汽车", "游戏"]})
    ak.stock_zt_pool_em = zt
    ak.stock_zt_pool_zbgc_em = lambda date: pd.DataFrame({"代码": ["600009"]})
    ak.stock_zt_pool_dtgc_em = lambda date: pd.DataFrame()      # a real zero on an observed day
    ak.stock_zt_pool_previous_em = lambda date: pd.DataFrame({"涨跌幅": [4.0, -1.0]})
    text = sentiment.get_market_sentiment("2026-11-13", "000026.SZ")
    assert "| 2026-11-13 | 4 | 1 | 20.0% | 0 | 3 | 2 | +1.50% |" in text
    assert "Unobserved days" in text and "2026-11-10" in text
    assert "3板 1家 (飞亚达)" in text and "汽车 2" in text
    assert "000026.SZ in the pools: 11-11 涨停" in text


def test_market_sentiment_with_no_observed_day_says_so(ak):
    ak.stock_zt_pool_em = _boom
    text = sentiment.get_market_sentiment("2026-03-02")
    assert "unavailable" in text and "unobserved" in text


# ---------------------------------------------------------------------------
# 人气
# ---------------------------------------------------------------------------
def test_popularity_stops_at_the_trade_date(ak):
    days = pd.date_range("2026-10-01", "2026-11-15")
    ak.stock_hot_rank_detail_em = lambda symbol: pd.DataFrame({
        "时间": days.strftime("%Y-%m-%d"), "排名": range(len(days), 0, -1), "证券代码": symbol,
        "新晋粉丝": 0.3, "铁杆粉丝": 0.7})
    ak.stock_comment_detail_zhpj_lspf_em = lambda symbol: pd.DataFrame({"交易日": ["2026-11-12", "2026-11-13"], "评分": [70.0, 80.0]})
    ak.stock_comment_detail_scrd_focus_em = lambda symbol: pd.DataFrame({"交易日": ["2026-11-13"], "用户关注指数": [90.0]})
    ak.stock_comment_detail_scrd_desire_em = _boom
    text = sentiment.get_popularity("600519.SS", "2026-11-12")
    assert "| 2026-11-12 |" in text and "2026-11-13" not in text and "2026-11-15" not in text
    assert "30.0%" in text and "| 2026-11-12 | 70.0 | — |" in text


# ---------------------------------------------------------------------------
# The sentiment analyst
# ---------------------------------------------------------------------------
class _LLM:
    def __init__(self):
        self.prompt = None

    def with_structured_output(self, *a, **k):
        raise NotImplementedError

    def invoke(self, messages):
        from langchain_core.messages import AIMessage
        self.prompt = "\n".join(str(m.content) for m in messages)
        return AIMessage(content="report")


@pytest.fixture(autouse=True)
def _no_real_market_temperature(monkeypatch):
    """The market-temperature block reads the local store and the network: stubbed here."""
    from tradingagents.agents.analysts import sentiment_analyst as sa
    monkeypatch.setattr(sa, "get_market_temperature", lambda d, t: f"TEMPERATURE {d} {t}")
    monkeypatch.setattr(sa, "get_broad_etf_flow", lambda d: f"ETF加仓指数 {d}")


def test_an_a_share_reads_akshare_blocks_not_stocktwits_or_reddit(monkeypatch):
    from tradingagents.agents.analysts import sentiment_analyst as sa

    monkeypatch.setattr(sa.get_news, "func", lambda *a: "东财新闻")
    for name in ("fetch_stocktwits_messages", "fetch_reddit_posts", "jev_screen"):
        monkeypatch.setattr(sa, name, lambda *a, **k: pytest.fail("social feeds are not read for an A-share"))
    monkeypatch.setattr(sa.ashare_sentiment, "get_fund_sentiment", lambda t, d: f"FUND {t} {d}")
    monkeypatch.setattr(sa.ashare_sentiment, "get_market_sentiment", lambda d, t: f"MARKET {d}")
    monkeypatch.setattr(sa.ashare_sentiment, "get_popularity", lambda t, d: _boom())
    llm = _LLM()
    out = sa.create_sentiment_analyst(llm)({"company_of_interest": "600519.SS", "trade_date": "2026-11-13",
                                           "messages": []})
    assert out["sentiment_report"]
    assert "FUND 600519.SS 2026-11-13" in llm.prompt and "MARKET 2026-11-13" in llm.prompt
    assert "TEMPERATURE 2026-11-13 600519.SS" in llm.prompt          # with block 2, the market's temperature
    assert "ETF加仓指数 2026-11-13" in llm.prompt                     # and the broad-based ETFs' 加仓指数
    assert "<unavailable: ConnectionError" in llm.prompt
    assert "东财新闻" in llm.prompt and "StockTwits" not in llm.prompt


def test_a_us_stock_still_reads_the_social_feeds(monkeypatch):
    from tradingagents.agents.analysts import sentiment_analyst as sa

    seen = []
    monkeypatch.setattr(sa.get_news, "func", lambda *a: "news")
    monkeypatch.setattr(sa, "jev_screen", lambda t: None)
    monkeypatch.setattr(sa, "fetch_stocktwits_messages", lambda *a, **k: seen.append("st") or "")
    monkeypatch.setattr(sa, "fetch_reddit_posts", lambda *a, **k: seen.append("rd") or "")
    monkeypatch.setattr(sa.ashare_sentiment, "get_fund_sentiment", lambda *a: pytest.fail("not an A-share"))
    sa.create_sentiment_analyst(_LLM())({"company_of_interest": "NVDA", "trade_date": "2026-11-13", "messages": []})
    assert seen == ["st", "rd"]


# ---------------------------------------------------------------------------
# The report, scored block by block
# ---------------------------------------------------------------------------
def _block(block, band, score, confidence="medium", evidence="e"):
    from tradingagents.agents.schemas import BlockSentiment
    return BlockSentiment(block=block, band=band, score=score, confidence=confidence, key_evidence=evidence)


def test_the_a_share_report_keeps_the_header_and_scores_each_block():
    from tradingagents.agents.schemas import (
        AShareSentimentReport,
        SentimentBand,
        SentimentBlock,
        render_ashare_sentiment_report,
    )
    report = AShareSentimentReport(
        blocks=[_block(SentimentBlock.MARKET, SentimentBand.BEARISH, 3.5, "high", "炸板率 48.6%"),
                _block(SentimentBlock.FUND, SentimentBand.MILDLY_BEARISH, 4.2, evidence="主力 10日 -9.88亿 | 融资 -0.7%"),
                _block(SentimentBlock.FUND, SentimentBand.BULLISH, 9.0)],      # a repeat keeps the first
        overall_band=SentimentBand.MILDLY_BEARISH, overall_score=4.4, confidence="medium", narrative="## 资金情绪\n...")
    md = render_ashare_sentiment_report(report)
    lines = md.splitlines()
    assert lines[0] == "**Overall Sentiment:** **Mildly Bearish** (Score: 4.4/10)"
    assert lines[1] == "**Confidence:** Medium"
    rows = [line for line in lines if line.startswith("| ") and "Block" not in line]
    assert [r.split(" | ")[0][2:] for r in rows] == ["资金情绪", "市场情绪", "人气", "新闻"], "fixed order"
    assert "| 资金情绪 | Mildly Bearish | 4.2 | Medium | 主力 10日 -9.88亿 / 融资 -0.7% |" in md
    assert "| 人气 | not assessed |" in md and "9.0" not in md
    assert md.endswith("## 资金情绪\n...")


def test_an_a_share_run_asks_for_the_block_scored_report(monkeypatch):
    from unittest.mock import MagicMock

    from tradingagents.agents.analysts import sentiment_analyst as sa
    from tradingagents.agents.schemas import (
        AShareSentimentReport,
        SentimentBand,
        SentimentBlock,
        SentimentReport,
    )

    monkeypatch.setattr(sa.get_news, "func", lambda *a: "news")
    for name in ("get_fund_sentiment", "get_market_sentiment", "get_popularity"):
        monkeypatch.setattr(sa.ashare_sentiment, name, lambda *a: "block")
    monkeypatch.setattr(sa, "fetch_stocktwits_messages", lambda *a, **k: "")
    monkeypatch.setattr(sa, "fetch_reddit_posts", lambda *a, **k: "")
    monkeypatch.setattr(sa, "jev_screen", lambda t: None)
    results = {
        AShareSentimentReport: AShareSentimentReport(
            blocks=[_block(b, SentimentBand.NEUTRAL, 5.0) for b in SentimentBlock],
            overall_band=SentimentBand.NEUTRAL, overall_score=5.0, confidence="low", narrative="n"),
        SentimentReport: SentimentReport(overall_band=SentimentBand.NEUTRAL, overall_score=5.0,
                                         confidence="low", narrative="n"),
    }
    prompts = {}

    def bind(schema):
        structured = MagicMock()
        structured.invoke.side_effect = lambda p: prompts.__setitem__(schema, p) or results[schema]
        return structured
    llm = MagicMock()
    llm.with_structured_output.side_effect = bind
    node = sa.create_sentiment_analyst(llm)
    a = node({"company_of_interest": "600519.SS", "trade_date": "2026-11-13", "messages": []})["sentiment_report"]
    assert "**Sentiment by block:**" in a and "| 市场情绪 | Neutral | 5.0 |" in a
    assert "exactly one entry per block" in str(prompts[AShareSentimentReport])
    us = node({"company_of_interest": "NVDA", "trade_date": "2026-11-13", "messages": []})["sentiment_report"]
    assert "Sentiment by block" not in us and us.startswith("**Overall Sentiment:** **Neutral**")


def ths_table(symbol):
    if symbol == "即时":
        return pd.DataFrame({"序号": [1], "股票代码": ["300308"], "股票简称": ["中际旭创"], "最新价": [465.0],
                             "涨跌幅": ["-8.63%"], "换手率": ["4.66%"], "流入资金": ["121.58亿"],
                             "流出资金": ["126.92亿"], "净额": ["-5.33亿"], "成交额": ["249.87亿"]})
    return pd.DataFrame({"序号": [1], "股票代码": ["300308"], "股票简称": ["中际旭创"], "最新价": [465.0],
                         "阶段涨跌幅": ["3.79%"], "连续换手率": ["23.57%"], "资金流入净额": ["24.83亿"]})


def test_ths_serves_the_latest_session_when_eastmoney_cannot(ak):
    calls = []
    ak.stock_individual_fund_flow = _boom
    ak.stock_fund_flow_individual = lambda symbol: calls.append(symbol) or ths_table(symbol)
    text = sentiment._fund_flow("300308", TODAY)                   # Saturday: the latest session is 11-13
    assert "Source: 同花顺 (THS)" in text and "ConnectionError: down" in text and "Session 2026-11-13" in text
    assert "| 当日 | -8.63% | 4.66% | -5.33亿 | 121.58亿 | 126.92亿 | 249.87亿 |" in text
    assert "| 20日 | 3.79% | 23.57% | +24.83亿 | — | — | — |" in text
    assert "must not be compared" in text
    sentiment._fund_flow("300308", TODAY)
    assert calls == ["即时", "5日排行", "10日排行", "20日排行"], "the session's tables are cached"


def test_ths_cannot_serve_a_past_session(ak):
    ak.stock_individual_fund_flow = _boom
    ak.stock_fund_flow_individual = lambda symbol: pytest.fail("no history to read")
    text = sentiment._section("x", "fund flow", lambda: sentiment._fund_flow("300308", "2026-11-10"))
    assert "Eastmoney ConnectionError: down" in text and "同花顺 fallback: 同花顺 serves only the latest session" in text
