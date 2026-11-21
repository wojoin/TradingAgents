"""A stock's main-force net inflow (主力净流入) day by day, for the stock page's card.

Eastmoney's per-stock fund flow (``stock_individual_fund_flow``) keeps only about the last 120
trading days, so each fetch is merged into ``.akshare_data/web/flow/<code>.parquet``: the history
grows the more a stock is looked at; the days the market snapshots keep (their appended
``main_flow`` column) are added too. The download itself is the sentiment analyst's (once a day,
cached under agent/fund_flow/). When Eastmoney cannot be reached, what is on disk is served.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from tradingagents.dataflows.symbols import a_share_code, exchange_prefix
from tradingagents.dataflows.vendors.akshare import store

log = logging.getLogger(__name__)


def _path(code: str) -> Path:
    return store.root() / "web" / "flow" / f"{code}.parquet"


def _download(code: str) -> pd.DataFrame:
    from tradingagents.dataflows.vendors.akshare import sentiment
    market = exchange_prefix(code).lower()
    raw = sentiment._per_stock("fund_flow", code,
                               lambda: store.ak().stock_individual_fund_flow(stock=code, market=market),
                               "Eastmoney fund flow")
    if raw.empty:
        return pd.DataFrame(columns=["date", "main"])
    return pd.DataFrame({"date": pd.to_datetime(raw["日期"], errors="coerce").dt.strftime("%Y-%m-%d"),
                         "main": pd.to_numeric(raw["主力净流入-净额"], errors="coerce")}).dropna()


def history(code: str, fetch=None) -> dict:
    c = a_share_code(code)
    if not c or not exchange_prefix(c):
        raise LookupError(f"{code} is not an A-share stock")
    path = _path(c)
    kept = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["date", "main"])
    note = None
    try:
        new = (fetch or _download)(c)
    except Exception as e:  # noqa: BLE001 - rate-limited or down: what is kept still serves
        log.info("fund flow for %s unavailable: %s", c, e)
        new = pd.DataFrame(columns=["date", "main"])
        note = f"东方财富资金流暂不可用（{type(e).__name__}），显示本地已存的数据"
    df = (pd.concat([kept, new], ignore_index=True).dropna()
          .drop_duplicates("date", keep="last").sort_values("date"))
    # The days the market snapshots keep (main_flow appended after each session), where Eastmoney's
    # per-stock history does not reach; only its 主力净流入 measure (not 同花顺's).
    try:
        from tradingagents.dataflows.vendors.akshare import snapshots
        snap = snapshots.load_daily_extra(c)
        if len(snap):
            snap = snap[snap["main_flow_src"].fillna("eastmoney") == "eastmoney"] if "main_flow_src" in snap else snap
            snap = pd.DataFrame({"date": pd.to_datetime(snap["trade_date"]).dt.strftime("%Y-%m-%d"),
                                 "main": pd.to_numeric(snap["main_flow"], errors="coerce")}).dropna()
            df = (pd.concat([snap, df], ignore_index=True)
                  .drop_duplicates("date", keep="last").sort_values("date"))
    except Exception as e:  # noqa: BLE001 - the snapshots only add days
        log.info("snapshot flows for %s unreadable: %s", c, e)
    if len(new):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        df.to_parquet(tmp, index=False)
        tmp.replace(path)
    return {"symbol": c, "since": df["date"].iloc[0] if len(df) else None, "note": note,
            "days": {d: float(v) for d, v in zip(df["date"], df["main"], strict=True)}}
