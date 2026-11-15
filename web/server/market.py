"""The whole A-share market for the web pages: quotes, industries, main-force flow, search.

  quotes      the daily cross-section the AKShare store keeps under
              ``.akshare_data/snapshots/<YYYYMMDD>/cross_section.parquet`` (every A-share's
              close, change, turnover, amount and volume in lots)
  industries  Shenwan level 1 and 2 from the store's constituent tables
  main flow   Eastmoney's 今日主力净流入 for the latest session (cached for the session);
              when Eastmoney is unreachable, 同花顺's 资金净流入 for that session, which is a
              different measure and is labelled so; for an older date, whichever was cached
  search      a code prefix or a name fragment, against the latest cross-section

Names and industries are today's; they label the table and resolve a name typed
into the analysis box to a code.
"""
from __future__ import annotations

import re
import threading
from functools import lru_cache
from pathlib import Path

import pandas as pd

from tradingagents.dataflows.symbols import a_share_code, normalize_symbol
from tradingagents.dataflows.vendors.akshare import settings as ak_settings, store

XS_FILE = "cross_section.parquet"
_LOCK = threading.Lock()
_TABLES: dict[tuple[str, str], dict] = {}   # (date, flow source) -> table, for the process


def snapshot_root() -> Path:
    return ak_settings.data_dir() / "snapshots"


def available_dates() -> list[str]:
    """Trading days with a whole-market cross-section on disk, newest first (YYYY-MM-DD)."""
    root = snapshot_root()
    if not root.is_dir():
        return []
    days = [d.name for d in root.iterdir() if re.fullmatch(r"\d{8}", d.name) and (d / XS_FILE).is_file()]
    return [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in sorted(days, reverse=True)]


def cross_section(date: str | None = None) -> tuple[str, pd.DataFrame]:
    """(date, the day's cross-section); the latest day when ``date`` is None."""
    dates = available_dates()
    if not dates:
        raise FileNotFoundError("no market snapshot under .akshare_data/snapshots; run `tradingagents-ashare sync`")
    day = date or dates[0]
    if day not in dates:
        raise FileNotFoundError(f"no market snapshot for {day}; available: {', '.join(dates[:10])}")
    return day, _read_xs(day.replace("-", ""))


@lru_cache(maxsize=8)
def _read_xs(day: str) -> pd.DataFrame:
    df = pd.read_parquet(snapshot_root() / day / XS_FILE)
    df["code"] = df["code"].astype(str).str.zfill(6)
    return df


def _latest(pattern: str) -> pd.DataFrame | None:
    files = sorted(ak_settings.data_dir().glob(pattern))
    return pd.read_pickle(files[-1]) if files else None


@lru_cache(maxsize=1)
def industries() -> pd.DataFrame:
    """code -> sw1, sw2 (Shenwan names), from the store's latest constituent tables."""
    def level(members: str, names: str, code_col: str, label: str) -> pd.DataFrame:
        cons, table = _latest(members), _latest(names)
        if cons is None or table is None:
            return pd.DataFrame(columns=["code", label])
        lookup = dict(zip(table["行业代码"].astype(str).str.extract(r"(\d{6})")[0], table["行业名称"], strict=False))
        return pd.DataFrame({"code": cons["证券代码"].astype(str).str.zfill(6),
                             label: cons[code_col].astype(str).str.extract(r"(\d{6})")[0].map(lookup)})

    sw1 = level("sw_comp__*.pkl", "sw_first__*.pkl", "行业代码", "sw1").drop_duplicates("code")
    sw2 = level("sw_second_cons__*.pkl", "sw_second__*.pkl", "二级代码", "sw2").drop_duplicates("code")
    return sw1.merge(sw2, on="code", how="outer").set_index("code")


# ---------------------------------------------------------------------------
# Main-force flow
# ---------------------------------------------------------------------------
def _cached_table(kind: str, key: str) -> pd.DataFrame | None:
    path = store.root() / "sentiment" / kind / f"{key}.pkl"
    return pd.read_pickle(path) if path.exists() else None


def main_flow(date: str) -> tuple[pd.Series | None, dict]:
    """(code -> net inflow in yuan, source note) for the session ``date``."""
    from tradingagents.dataflows.vendors.akshare.insiders import cn_number
    from tradingagents.dataflows.vendors.akshare.sentiment import _dated

    key = date.replace("-", "")
    latest = pd.Timestamp(date).date() >= store.last_closed_trade_date()
    final = not store.is_intraday()
    em_error = None
    em = _cached_table("em_fund_flow_today", key)
    if em is None and latest:
        try:
            em = _dated("em_fund_flow_today", key, final,
                        lambda: store.ak().stock_individual_fund_flow_rank(indicator="今日"), "Eastmoney fund flow rank")
        except Exception as e:  # noqa: BLE001 — Eastmoney rate-limits; 同花顺 stands in
            em_error = f"{type(e.__cause__ or e).__name__}"
    if em is not None and len(em) and "今日主力净流入-净额" in em:
        flow = pd.to_numeric(em["今日主力净流入-净额"], errors="coerce")
        flow.index = em["代码"].astype(str).str.zfill(6)
        return flow, {"source": "eastmoney", "label": "主力净流入", "note": "东方财富 今日主力净流入"}
    ths = _cached_table("ths_fund_flow_now", key)
    if ths is None and latest:
        try:
            ths = _dated("ths_fund_flow_now", key, final,
                         lambda: store.ak().stock_fund_flow_individual(symbol="即时"), "同花顺 fund flow")
        except Exception:  # noqa: BLE001
            ths = None
    if ths is not None and len(ths) and "净额" in ths:
        flow = ths["净额"].map(cn_number)
        flow.index = ths["股票代码"].astype(str).str.zfill(6)
        why = f"东方财富不可用（{em_error}）" if em_error else "东方财富当日数据未缓存"
        return flow, {"source": "ths", "label": "资金净流入(同花顺)",
                      "note": f"{why}，改用同花顺口径：按主动买卖方向统计全部成交，不分主力，不能与主力净流入比较"}
    reason = "只有最新交易日能取到" if not latest else (f"东方财富 {em_error}，同花顺也不可用" if em_error else "数据源不可用")
    return None, {"source": None, "label": "主力净流入", "note": f"{date} 的资金流不可得：{reason}"}


# ---------------------------------------------------------------------------
# Tables and lookups
# ---------------------------------------------------------------------------
def _num(v):
    return None if pd.isna(v) else float(v)


def market_table(date: str | None = None) -> dict:
    """Every A-share on ``date`` (latest by default) with industry and main-force flow."""
    day, xs = cross_section(date)
    flow, flow_meta = main_flow(day)
    cache_key = (day, str(flow_meta.get("source")))
    with _LOCK:
        if cache_key in _TABLES:
            return _TABLES[cache_key]
    ind = industries()
    df = xs[["code", "name", "pct_chg", "close", "turnover", "amount", "volume", "total_mv"]].copy()
    df = df.join(ind, on="code")
    df["main_flow"] = df["code"].map(flow) if flow is not None else None
    rows = [{
        "code": r.code, "name": re.sub(r"\s+", "", str(r.name)), "pct_chg": _num(r.pct_chg), "price": _num(r.close),
        "main_flow": _num(r.main_flow), "industry": r.sw1 if isinstance(r.sw1, str) else None,
        "sub_industry": r.sw2 if isinstance(r.sw2, str) else None, "turnover": _num(r.turnover),
        "amount": _num(r.amount), "volume": _num(r.volume), "total_mv": _num(r.total_mv),
    } for r in df.itertuples(index=False)]
    table = {"date": day, "dates": available_dates(), "flow": flow_meta, "count": len(rows), "rows": rows}
    with _LOCK:
        _TABLES[cache_key] = table
    return table


def _names() -> pd.DataFrame:
    _, xs = cross_section()
    out = xs[["code", "name"]].copy()
    out["name"] = out["name"].astype(str).str.replace(r"\s+", "", regex=True)
    out["plain"] = out["name"].str.replace(r"^\*?S?\*?ST", "", regex=True).str.upper()
    return out


def search(q: str, limit: int = 10) -> list[dict]:
    """Stocks whose code starts with ``q`` or whose name contains it; exact matches first."""
    q = re.sub(r"\s+", "", q or "").upper()
    if not q:
        return []
    df = _names()
    code_q = re.sub(r"^(SH|SZ|BJ)|\.(SS|SH|SZ|BJ)$", "", q)
    hit = df[df["code"].str.startswith(code_q) | df["name"].str.upper().str.contains(q, regex=False)
             | df["plain"].str.contains(q, regex=False)]
    hit = hit.assign(rank=(hit["code"] != code_q) & (hit["name"].str.upper() != q) & (hit["plain"] != q))
    hit = hit.sort_values(["rank", "code"]).head(limit)
    return [{"code": r.code, "name": r.name, "symbol": normalize_symbol(r.code)} for r in hit.itertuples()]


def resolve_ticker(q: str) -> str:
    """A stock code from a code or a name; raises ValueError naming the candidates when unsure.

    A-share codes and foreign tickers (AAPL, 0700.HK) pass through; a Chinese name
    must match exactly one stock, or be the only one containing it.
    """
    raw = (q or "").strip()
    if not raw:
        raise ValueError("请输入股票代码或名称")
    if a_share_code(raw) or re.fullmatch(r"[A-Za-z0-9.\-^=]{1,20}", raw):
        return raw
    try:
        found = search(raw, limit=20)
    except FileNotFoundError as e:
        raise ValueError(f"无法按名称查找股票：{e}") from e
    key = re.sub(r"\s+", "", raw).upper()
    exact = [f for f in found if f["name"].upper() == key or re.sub(r"^\*?S?\*?ST", "", f["name"]).upper() == key]
    if len(exact) == 1:
        return exact[0]["code"]
    if len(found) == 1:
        return found[0]["code"]
    if not found:
        raise ValueError(f"找不到名称包含「{raw}」的股票")
    names = "、".join(f"{f['name']}({f['code']})" for f in found[:8])
    raise ValueError(f"「{raw}」对应多只股票：{names}，请输入代码或完整名称")


def quote(code: str) -> dict | None:
    """One stock's row of the latest market table."""
    code = a_share_code(code) or code
    table = market_table()
    for row in table["rows"]:
        if row["code"] == code:
            return {**row, "date": table["date"], "flow": table["flow"], "symbol": normalize_symbol(code)}
    return None


# ---------------------------------------------------------------------------
# A stock's whole daily history from the local store
# ---------------------------------------------------------------------------
def base_through() -> str | None:
    """The last day ``snapshots/base`` covers (YYYY-MM-DD), from the store's _meta.json."""
    import json

    try:
        day = json.loads((snapshot_root() / "_meta.json").read_text()).get("base_through")
    except (OSError, ValueError):
        return None
    return f"{day[:4]}-{day[4:6]}-{day[6:]}" if day and len(day) == 8 else None


def history(code: str, end: str | None = None) -> dict:
    """Every daily bar of an A-share since listing: ``snapshots/base`` (to base_through)
    then the daily cross-sections after it. Prices are unadjusted; volume is in lots (手).

    Raises FileNotFoundError when the store has no data for the stock.
    """
    from tradingagents.dataflows.symbols import exchange_prefix
    from tradingagents.dataflows.vendors.akshare.snapshots import load_stock

    c = a_share_code(code)
    ex = exchange_prefix(c) if c else None
    if not ex:
        raise FileNotFoundError(f"{code} is not an A-share stock")
    df = load_stock(f"{ex}{c}", end)
    df = df.dropna(subset=["open", "high", "low", "close"])
    through = base_through()
    bars = [{"time": f"{r.trade_date:%Y-%m-%d}", "open": float(r.open), "high": float(r.high), "low": float(r.low),
             "close": float(r.close), "volume": _num(r.volume), "amount": _num(r.amount), "pct_chg": _num(r.pct_chg),
             "turnover": _num(r.turnover)} for r in df.itertuples(index=False)]
    after = sum(1 for b in bars if through and b["time"] > through)
    return {
        "symbol": normalize_symbol(c), "name": re.sub(r"\s+", "", str(df["name"].iloc[-1])) if len(df) else None,
        "source": "snapshot", "adjust": "不复权", "volume_unit": "手",
        "base_through": through, "after_base": after, "bars": bars,
    }
