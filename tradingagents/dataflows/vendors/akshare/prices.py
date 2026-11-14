"""A-share daily bars for the analysts: forward-adjusted OHLCV, indicators, closes.

Prices are forward-adjusted (前复权), like Yahoo's ``auto_adjust``: a bonus-share
or dividend ex-date would otherwise read as a crash to every moving average.
The unadjusted snapshots in ``.akshare_data/snapshots`` cannot be adjusted
locally (the history carries no ex-rights factors), so the adjusted bars are
fetched per stock, Sina first and Eastmoney second, and cached for the day.
"""
from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError
from tradingagents.dataflows.symbols import a_share_code, exchange_prefix, normalize_symbol
from tradingagents.dataflows.vendors.akshare import store

logger = logging.getLogger(__name__)

HISTORY_YEARS = 5
# A-share holidays (Spring Festival, National Day) close the market for up to
# nine calendar days, so the staleness bar sits above Yahoo's ten days.
MAX_STALE_DAYS = 15
OHLCV = ["Date", "Open", "High", "Low", "Close", "Volume"]
SOURCES = ("sina", "eastmoney")


def require_code(symbol: str) -> str:
    """The 6-digit code of an A-share stock symbol; anything else has no data here."""
    code = a_share_code(symbol)
    if code is None:
        raise NoMarketDataError(symbol, normalize_symbol(symbol), "not a China A-share stock")
    return code


def _from_sina(code: str, start: str, end: str) -> pd.DataFrame:
    raw = store.ak().stock_zh_a_daily(symbol=f"{exchange_prefix(code).lower()}{code}",
                                      start_date=start, end_date=end, adjust="qfq")
    if raw is None or raw.empty:
        return pd.DataFrame(columns=[*OHLCV, "Amount", "Turnover"])
    return pd.DataFrame({
        "Date": raw["date"], "Open": raw["open"], "High": raw["high"], "Low": raw["low"],
        "Close": raw["close"], "Volume": raw["volume"],               # shares
        "Amount": raw["amount"], "Turnover": pd.to_numeric(raw["turnover"], errors="coerce") * 100,
    })


def _from_eastmoney(code: str, start: str, end: str) -> pd.DataFrame:
    raw = store.ak().stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")
    if raw is None or raw.empty:
        return pd.DataFrame(columns=[*OHLCV, "Amount", "Turnover"])
    return pd.DataFrame({
        "Date": raw["日期"], "Open": raw["开盘"], "High": raw["最高"], "Low": raw["最低"],
        "Close": raw["收盘"], "Volume": pd.to_numeric(raw["成交量"], errors="coerce") * 100,  # lots -> shares
        "Amount": raw["成交额"], "Turnover": raw["换手率"],
    })


def _download(code: str) -> pd.DataFrame:
    today = store.now_cst().date()
    start = (today - dt.timedelta(days=365 * HISTORY_YEARS)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    errors, answered_empty = [], False
    for source in SOURCES:
        fetch = _from_sina if source == "sina" else _from_eastmoney
        try:
            df = fetch(code, start, end)
        except Exception as e:
            errors.append(f"{source}: {type(e).__name__}: {str(e)[:120]}")
            continue
        if df.empty:
            answered_empty = True
            continue
        return df
    if answered_empty:
        return pd.DataFrame(columns=[*OHLCV, "Amount", "Turnover"])
    raise VendorUnavailableError(f"AKShare daily bars failed for {code} ({'; '.join(errors)})")


def history(symbol: str, as_of_date: str | None = None) -> pd.DataFrame:
    """Forward-adjusted daily bars up to ``as_of_date`` (inclusive), oldest first."""
    code = require_code(symbol)
    sym = store.to_symbol(code)
    live = as_of_date is None or as_of_date >= store.now_cst().date().isoformat()
    data = store.symbol_cache("ohlcv", sym, lambda: _download(code), live=live)
    if data.empty:
        raise NoMarketDataError(symbol, normalize_symbol(symbol), "no daily bars")
    data = data.copy()
    data["Date"] = pd.to_datetime(data["Date"]).dt.normalize()
    for c in data.columns.drop("Date"):
        data[c] = pd.to_numeric(data[c], errors="coerce")
    data = data.sort_values("Date").dropna(subset=["Close"])
    if as_of_date:
        data = data[data["Date"] <= pd.Timestamp(as_of_date)]
    if data.empty:
        raise NoMarketDataError(symbol, normalize_symbol(symbol), f"no daily bars on or before {as_of_date}")
    return data.reset_index(drop=True)


def _assert_not_stale(data: pd.DataFrame, as_of_date: str, symbol: str) -> None:
    latest = data["Date"].max()
    gap = (pd.Timestamp(as_of_date).normalize() - latest).days
    if gap > MAX_STALE_DAYS:
        raise NoMarketDataError(
            symbol, normalize_symbol(symbol),
            f"latest bar is {latest.date()}, {gap} days before the requested {as_of_date} "
            f"(suspended or delisted?) — refusing to use it")


def load_ohlcv(symbol: str, as_of_date: str, fill_gaps: bool = True) -> pd.DataFrame:
    """Date/Open/High/Low/Close/Volume up to ``as_of_date``, the frame the indicator
    and snapshot code reads (same contract as the Yahoo loader).

    ``fill_gaps`` is accepted for that contract; the bars come without gaps
    (a suspended day has no bar, rather than an empty one)."""
    data = history(symbol, as_of_date)
    _assert_not_stale(data, as_of_date, symbol)
    data = data[OHLCV].reset_index(drop=True)
    data["Volume"] = data["Volume"].fillna(0).round().astype("int64")
    return data


def _price(v: float) -> str:
    return "" if pd.isna(v) else f"{v:.2f}"


def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """Daily bars between the dates, forward-adjusted, as CSV."""
    data = history(symbol, end_date)
    _assert_not_stale(data, end_date, symbol)
    window = data[data["Date"] >= pd.Timestamp(start_date)]
    if window.empty:
        raise NoMarketDataError(symbol, normalize_symbol(symbol), f"no bars between {start_date} and {end_date}")
    out = window.copy()
    out["Date"] = out["Date"].dt.strftime("%Y-%m-%d")
    for c in ("Open", "High", "Low", "Close"):
        out[c] = out[c].map(_price)
    out["Volume"] = out["Volume"].round().astype("Int64")
    out["Amount"] = out["Amount"].round().astype("Int64")
    out["Turnover"] = out["Turnover"].round(3)
    canonical = normalize_symbol(symbol)
    header = (
        f"# Stock data for {canonical} from {start_date} to {end_date}\n"
        f"# Total records: {len(out)}\n"
        f"# China A-share daily bars: prices forward-adjusted (前复权) in CNY; "
        f"Volume in shares; Amount in CNY; Turnover in % of float\n\n"
    )
    return header + out.to_csv(index=False)


def get_indicators(symbol: str, indicator: str, as_of_date: str, look_back_days: int) -> str:
    """A technical indicator over the window, computed on the forward-adjusted bars."""
    from tradingagents.dataflows.vendors.yahoo.market import get_stock_stats_indicators_window
    return get_stock_stats_indicators_window(symbol, indicator, as_of_date, look_back_days, loader=load_ohlcv)


def get_closes(symbol: str, start_date: str, end_date: str) -> pd.Series:
    """Daily closes from ``start_date`` up to, not including, ``end_date``."""
    data = history(symbol)
    data = data[(data["Date"] >= pd.Timestamp(start_date)) & (data["Date"] < pd.Timestamp(end_date))]
    return pd.Series(data["Close"].to_numpy(), index=pd.DatetimeIndex(data["Date"]), name="Close")
