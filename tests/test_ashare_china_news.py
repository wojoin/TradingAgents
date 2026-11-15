"""China news about the stock under analysis (新闻联播 and the archived wires) for get_global_news.

Offline: akshare, the wires and the local profile are faked, the data directory is
temporary, and the clock is fixed at Saturday 2026-11-14 20:00 Beijing time.
"""
from __future__ import annotations

import types
from datetime import datetime, timedelta

import pandas as pd
import pytest

from tradingagents.agents import tools
from tradingagents.dataflows import router
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.vendors.akshare import china_news, fundamentals, settings, store

pytestmark = pytest.mark.unit

TODAY = "2026-11-14"
NOW = datetime(2026, 11, 14, 20, 0)
PROFILE = {"name": "贵州茅台", "sw1": "食品饮料", "sw2": "白酒Ⅱ"}


def cctv(date):
    return pd.DataFrame({
        "date": date,
        "title": ["国务院常务会议部署扩大内需", "白酒行业协会发布消费报告", "国内联播快讯"],
        "content": ["会议指出要提振消费。", "报告显示高端白酒动销平稳。",
                    "某地举办灯会。贵州茅台镇举办酒文化节。另一条与此无关。"],
    })


def item(i, hours_ago, title, body="", codes=""):
    return {"id": f"x{i}", "time": NOW - timedelta(hours=hours_ago), "title": title, "body": body, "codes": codes}


@pytest.fixture
def env(tmp_path, monkeypatch):
    settings.set_data_dir(tmp_path / ".akshare_data")
    fake = types.SimpleNamespace(cctv_calls=[], pages={"cls": [], "em": []})
    fake.news_cctv = lambda date: fake.cctv_calls.append(date) or cctv(date)
    monkeypatch.setattr(store, "ak", lambda: fake)
    monkeypatch.setattr(store, "now_cst", lambda: NOW.replace(tzinfo=store.CST))
    monkeypatch.setattr(fundamentals, "local_profile", lambda code: dict(PROFILE))
    fake.cls = [
        item(1, 2, "贵州茅台下调经销商代售价", "茅台精品酒下调至2359元/瓶。"),
        item(2, 3, "央行开展逆回购", "央行开展5000亿元逆回购操作。"),
        item(3, 30, "白酒板块午后活跃", "皇台酒业涨停。"),
        item(4, 40, "沙特反倾销调查", "税号721621600519项下的产品。"),
        item(5, 50, "主力资金监控", "宁德时代遭净卖出。", codes="600519"),
        item(6, 24 * 9, "茅台九天前的消息", "旧闻。"),
    ]
    fake.em = [item(11, 2, "贵州茅台下调经销商代售价！", "同一条新闻。"), item(12, 5, "方大集团公告", "无关。")]

    def pager(name):
        def page(cursor):
            fake.pages[name].append(cursor)
            rows = getattr(fake, name)
            i = cursor or 0
            got = rows[i:i + 2]
            return got, (i + 2 if i + 2 < len(rows) else None)
        return page
    monkeypatch.setitem(china_news.WIRES, "cls", ("财联社电报 (Cailian Press wire)", pager("cls"), 50))
    monkeypatch.setitem(china_news.WIRES, "em", ("东财快讯 (Eastmoney 7x24 wire)", pager("em"), 50))
    yield fake
    settings.set_data_dir(None)


def test_the_subject_s_names_and_industries():
    s = china_news.Subject("000002", "", china_news._name_variants("万 科Ａ", "000002"), ())
    assert s.names == ("万科", "000002")
    assert china_news._name_variants("贵州茅台", "600519") == ("贵州茅台", "茅台", "600519")
    assert china_news._name_variants("*ST金科", "000656")[0] == "金科"
    assert china_news._industries({"sw1": "食品饮料", "sw2": "白酒Ⅱ"}) == ("白酒", "食品饮料")
    assert not s.level("沙特调查", "税号721621000002项下"), "a code inside a longer number is no mention"


def test_only_items_about_the_stock_or_its_industry_are_kept(env):
    text = china_news.get_china_news("600519.SS", TODAY, 7)
    wire = text.split("## 财联社电报")[1].split("## 东财快讯")[0]
    assert "贵州茅台下调经销商代售价" in wire and "主力资金监控" in wire, "named or tagged"
    assert "Industry (1):" in wire and "白酒板块午后活跃" in wire
    assert "央行开展逆回购" not in text and "沙特反倾销" not in text and "方大集团" not in text
    assert "茅台九天前" not in text, "outside the window"


def test_cctv_quotes_the_matching_sentence_of_a_roundup(env):
    cctv_part = china_news.get_china_news("600519.SS", TODAY, 2).split("## 财联社")[0]
    assert "贵州茅台镇举办酒文化节。" in cctv_part and "灯会" not in cctv_part
    assert "白酒行业协会发布消费报告" in cctv_part and "国务院常务会议" not in cctv_part


def test_a_story_on_both_wires_is_listed_once(env):
    text = china_news.get_china_news("600519.SS", TODAY, 7)
    assert text.count("贵州茅台下调经销商代售价") == 1


def test_wires_are_archived_and_paged_only_back_to_the_archive(env, monkeypatch):
    china_news.get_china_news("600519.SS", TODAY, 7)
    first = len(env.pages["cls"])
    assert first == 3, "pages until an item is older than the 7-day backfill"
    # Two hours later only the newest page is read: the archive already reaches back.
    later = NOW + timedelta(hours=2)
    monkeypatch.setattr(store, "now_cst", lambda: later.replace(tzinfo=store.CST))
    env.cls.insert(0, item(7, -1, "茅台新消息", "新。"))
    text = china_news.get_china_news("600519.SS", "2026-11-14", 7)
    assert len(env.pages["cls"]) == first + 1 and "茅台新消息" in text


def test_a_past_window_beyond_the_archive_is_unobserved(env):
    text = china_news.get_china_news("600519.SS", "2026-10-01", 3)
    assert text.count("does not reach this window") == 2
    assert "### " not in text and "2026-10-01" in text


def test_a_total_outage_is_typed(env, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("down")
    env.news_cctv = boom
    for name in ("cls", "em"):
        monkeypatch.setitem(china_news.WIRES, name, (name, boom, 5))
    with run_config({}):
        out = router.route_to_vendor("get_china_news", "600519.SS", TODAY, 2)
    assert out.startswith("DATA_UNAVAILABLE")


def test_global_news_leads_with_china_for_an_a_share_only(monkeypatch):
    calls = []
    monkeypatch.setattr(tools, "route_to_vendor", lambda method, *a: calls.append((method, a)) or method.upper())
    out = tools.get_global_news.func("2026-11-13", 7, 5, trade_date="2026-11-13", ticker="600519.SS")
    assert out.index("GET_CHINA_NEWS") < out.index("GET_GLOBAL_NEWS")
    assert ("get_china_news", ("600519.SS", "2026-11-13", 7)) in calls
    calls.clear()
    assert tools.get_global_news.func("2026-11-13", 7, 5, trade_date="2026-11-13", ticker="NVDA") == "GET_GLOBAL_NEWS"
    assert [c[0] for c in calls] == ["get_global_news"]
    assert "ticker" not in tools.get_global_news.tool_call_schema.model_json_schema()["properties"]
