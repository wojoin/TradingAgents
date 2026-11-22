"""宽基ETF → 个股: what a day's share changes in the 20 funds come to in each stock.

A fund's shares grow when someone subscribes in kind: they hand the fund a basket of its index's
stocks at the index's weights. So a day's change in shares × the fund's close is money that went
into (or, on a redemption, came out of) the basket, and × each stock's weight is that stock's part.
Summed over the funds a stock is in (茅台 is in 上证50, 沪深300, 上证180 and 中证800), with each
fund's part kept.

It is an upper bound on new buying: a basket bought in the market that day is new money, one already
held and swapped for fund shares is not.

Weights: 中证指数 for its indices, 国证指数 (cnindex) for 创业板指 and 深证100, both published once a
month. Each snapshot is kept in ``.akshare_data/web/etf_weights.parquet`` (index, date, code, name,
weight); a day uses the latest snapshot on or before it, or the earliest there is.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import pandas as pd

from tradingagents.dataflows.vendors.akshare import store
from web.server import etf_flow

log = logging.getLogger(__name__)

# Each fund's index: (code, name). 159922 and 512500 are 中证500 like 510500, and so on.
INDEX = {
    "510300": ("000300", "沪深300"), "510310": ("000300", "沪深300"), "510330": ("000300", "沪深300"),
    "159919": ("000300", "沪深300"),
    "510500": ("000905", "中证500"), "159922": ("000905", "中证500"), "512500": ("000905", "中证500"),
    "512100": ("000852", "中证1000"), "560010": ("000852", "中证1000"), "159845": ("000852", "中证1000"),
    "159629": ("000852", "中证1000"),
    "510050": ("000016", "上证50"), "510180": ("000010", "上证180"), "510230": ("000018", "180金融"),
    "588080": ("000688", "科创50"), "588050": ("000688", "科创50"),
    "515800": ("000906", "中证800"),
    "159915": ("399006", "创业板指"), "159952": ("399006", "创业板指"), "159901": ("399330", "深证100"),
}
CNI = {"399006", "399330"}      # 国证指数's, the rest 中证指数's
TOP = 50                        # the stocks listed, by the size of what they came to
REFRESH_S = 24 * 3600           # an index's weights are asked for again after this (monthly anyway)

_lock = threading.Lock()
_asked: dict[str, float] = {}   # index -> when its weights were last asked for


def _path() -> Path:
    return store.root() / "web" / "etf_weights.parquet"


def fetch_weights(index: str) -> pd.DataFrame:
    """The index's latest published weights: date, code, name, weight (%)."""
    ak = store.ak()
    if index in CNI:
        df = ak.index_detail_cni(symbol=index)
        out = pd.DataFrame({"date": df["日期"].astype(str).str[:10], "code": df["样本代码"].astype(str).str.zfill(6),
                            "name": df["样本简称"], "weight": pd.to_numeric(df["权重"], errors="coerce")})
    else:
        df = ak.index_stock_cons_weight_csindex(symbol=index)
        out = pd.DataFrame({"date": pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d"),
                            "code": df["成分券代码"].astype(str).str.zfill(6), "name": df["成分券名称"],
                            "weight": pd.to_numeric(df["权重"], errors="coerce")})
    out = out.dropna(subset=["weight"])
    if out.empty:
        raise ValueError(f"no weights for {index}")
    return out


def weights(fetch=fetch_weights) -> pd.DataFrame:
    """Every snapshot on disk (index, date, code, name, weight), with each index's latest fetched
    at most once every REFRESH_S; an index that fails keeps what is on disk."""
    path = _path()
    with _lock:
        kept = pd.read_parquet(path) if path.exists() else pd.DataFrame(
            columns=["index", "date", "code", "name", "weight"])
        now, new = time.time(), []
        for index in sorted({i for i, _ in INDEX.values()}):
            if now - _asked.get(index, 0) < REFRESH_S:
                continue
            _asked[index] = now
            try:
                new.append(fetch(index).assign(index=index))
            except Exception as e:  # noqa: BLE001 — the snapshots on disk, then
                log.info("weights for %s: %s", index, e)
        if new:
            kept = pd.concat([kept, *new]) if len(kept) else pd.concat(new)
            kept = kept.drop_duplicates(["index", "date", "code"], keep="last").reset_index(drop=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            kept[["index", "date", "code", "name", "weight"]].to_parquet(path)
        return kept


def _snapshot(w: pd.DataFrame, index: str, day: str) -> pd.DataFrame:
    """The index's weights for ``day``: the latest snapshot on or before it, or the earliest."""
    mine = w[w["index"] == index]
    if mine.empty:
        return mine
    dates = sorted(mine["date"].unique())
    on = [d for d in dates if d <= day]
    return mine[mine["date"] == (on[-1] if on else dates[0])]


def implied(day: str | None = None, *, wide: pd.DataFrame | None = None, px: pd.DataFrame | None = None,
            w: pd.DataFrame | None = None, top: int = TOP) -> dict:
    """What ``day``'s (or the last day's) share changes come to in each stock, in 亿元.

    ``{date, total, funds: [{code, name, index, index_name, change, close, amount, weights_date}],
    stocks: [{code, name, amount, parts: [[fund code, 亿元]]}], count, note}``: funds by |amount|,
    the ``top`` stocks by |amount|, each stock's parts by |amount|; ``count`` is how many stocks
    there were in all.
    """
    if wide is None:
        with etf_flow._lock:
            wide, _, _ = etf_flow.update(etf_flow._trade_days())
    if wide.empty:
        raise FileNotFoundError("宽基ETF份额还没有下载到")
    days = list(wide.index)
    day = day or days[-1]
    if day not in days:
        on = [d for d in days if d <= day]
        if not on:
            raise FileNotFoundError(f"{day} 之前没有宽基ETF份额")
        day = on[-1]
    i = days.index(day)
    if i == 0:
        raise FileNotFoundError(f"{day} 是第一天，没有前一日可比")
    change = (wide.iloc[i] - wide.iloc[i - 1]).dropna()
    px = etf_flow.closes(day) if px is None else px
    close = px[px.index <= day].ffill().iloc[-1] if len(px) else pd.Series(dtype=float)
    w = weights() if w is None else w

    funds, parts, missing = [], [], []
    for code, dshares in change.items():
        index, index_name = INDEX[code]
        c = close.get(code)
        snap = _snapshot(w, index, day)
        if c is None or pd.isna(c) or snap.empty:
            missing.append(etf_flow.NAMES[code])
            continue
        amount = dshares * c / 1e8
        funds.append({"code": code, "name": etf_flow.NAMES[code], "index": index, "index_name": index_name,
                      "change": etf_flow._num(dshares / 1e8), "close": float(c), "amount": etf_flow._num(amount),
                      "weights_date": snap["date"].iloc[0]})
        if amount:
            parts.append(snap.assign(fund=code, amount=amount * snap["weight"] / 100)[["code", "name", "fund", "amount"]])
    funds.sort(key=lambda f: -abs(f["amount"]))

    stocks = []
    if parts:
        p = pd.concat(parts, ignore_index=True)
        names = p.drop_duplicates("code").set_index("code")["name"]
        by = p.groupby("code")["amount"].sum()
        by = by.reindex(by.abs().sort_values(ascending=False).index)
        for code, amount in by.iloc[:top].items():
            mine = p[p["code"] == code]
            mine = mine.reindex(mine["amount"].abs().sort_values(ascending=False).index)
            stocks.append({"code": code, "name": names[code], "amount": etf_flow._num(amount, 4),
                           "parts": [[f, etf_flow._num(a, 4)] for f, a in zip(mine["fund"], mine["amount"], strict=True)]})
        count = len(by)
    else:
        count = 0
    note = f"缺收盘价或权重，未计入：{'、'.join(missing)}" if missing else None
    return {"date": day, "total": etf_flow._num(sum(f["amount"] for f in funds)), "funds": funds,
            "stocks": stocks, "count": count, "note": note}
