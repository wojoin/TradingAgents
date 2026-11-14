"""A-share company news for the analysts, from Eastmoney (东方财富个股新闻).

The feed returns only the latest articles about a stock, whatever window is asked
for, so a window it did not reach is reported as unobserved, never as "no news"
(``date_window.coverage_gap``).
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.date_window import coverage_gap, in_window
from tradingagents.dataflows.symbols import normalize_symbol
from tradingagents.dataflows.vendors.akshare import store
from tradingagents.dataflows.vendors.akshare.prices import require_code

CST = ZoneInfo("Asia/Shanghai")
SUMMARY_CHARS = 400


def _articles(code: str) -> list[dict]:
    df = store.call(lambda: store.ak().stock_news_em(symbol=code), "Eastmoney news")
    if df is None or df.empty:
        return []
    out = []
    for _, row in df.iterrows():
        published = pd.to_datetime(row.get("发布时间"), errors="coerce")
        out.append({
            "title": str(row.get("新闻标题") or "No title").strip(),
            "summary": str(row.get("新闻内容") or "").strip(),
            "publisher": str(row.get("文章来源") or "Unknown").strip(),
            "link": str(row.get("新闻链接") or "").strip(),
            "pub_date": None if pd.isna(published) else published.to_pydatetime().replace(tzinfo=CST),
        })
    return sorted(out, key=lambda a: a["pub_date"] or datetime.min.replace(tzinfo=CST), reverse=True)


def _format(articles: list[dict]) -> str:
    out = ""
    for a in articles:
        when = f", {a['pub_date']:%Y-%m-%d %H:%M} Beijing time" if a["pub_date"] else ""
        out += f"### {a['title']} (source: {a['publisher']}{when})\n"
        if a["summary"]:
            summary = a["summary"]
            out += (summary[:SUMMARY_CHARS] + "…" if len(summary) > SUMMARY_CHARS else summary) + "\n"
        if a["link"]:
            out += f"Link: {a['link']}\n"
        out += "\n"
    return out


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    """Eastmoney news about the stock published in the window (Chinese-language articles)."""
    code = require_code(ticker)
    canonical = normalize_symbol(ticker)
    articles = _articles(code)[: get_config()["news_article_limit"] * 2]
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    in_range = [a for a in articles if in_window(a["pub_date"], start_dt, end_dt)]
    if in_range:
        return (f"## {canonical} News (Eastmoney, Chinese), from {start_date} to {end_date}:\n\n"
                + _format(in_range[: get_config()["news_article_limit"]]))
    subject = f"news for {canonical}"
    gap = coverage_gap((a["pub_date"] for a in articles), start_date, end_date, "Eastmoney news", subject)
    return gap or f"No news found for {canonical} between {start_date} and {end_date}"
