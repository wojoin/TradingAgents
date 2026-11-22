"""宽基ETF: the shares of the 20 broad-based ETFs the "national team" holds, day by day.

Their trading volume says little about money coming in or going out (a fund can be bought and sold to
itself all day), but their shares only move when units are created or redeemed, so the shares are where
the big money shows. Each day, for the 20 funds together:

- ``change``: the total shares against the day before, in 亿份 (the raw series: noisy day to day);
- ``index`` (加仓指数): total shares ÷ total on the base day × 100. It is the running sum of ``change``
  put on a base of 100, which is the same as weighting each fund's shares against its own base by its
  part of the base total; this is what turns the noise into a trend;
- ``rate5`` / ``rate20``: how far the index moved over the last 5 / 20 trading days, the speed of
  adding or redeeming.

The shares come from the exchanges: 上交所 publishes every ETF's shares for one day per request,
深交所 one fund over a span (a month is safe; a year returns nothing). They are kept in
``.akshare_data/web/etf_shares.parquet`` (date, code, shares) and topped up with the trading days not on
disk. A day either exchange has not published yet is left out, never counted as zero, and asked for
again after half an hour.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

import pandas as pd
import requests

from tradingagents.dataflows.vendors.akshare import store

log = logging.getLogger(__name__)

# (code, name, exchange). The order is only where a list starts: the page and the analysts rank the
# funds by each day's own size (shares × that day's close, see ``sizes``), which moves from day to day.
FUNDS: list[tuple[str, str, str]] = [
    ("510300", "沪深300ETF华泰柏瑞", "SH"),
    ("159915", "创业板ETF易方达", "SZ"),
    ("510310", "沪深300ETF易方达", "SH"),
    ("159919", "沪深300ETF嘉实", "SZ"),
    ("510330", "沪深300ETF华夏", "SH"),
    ("510500", "中证500ETF南方", "SH"),
    ("510050", "上证50ETF华夏", "SH"),
    ("588080", "科创50ETF易方达", "SH"),
    ("512100", "中证1000ETF南方", "SH"),
    ("159952", "创业板ETF广发", "SZ"),
    ("510180", "上证180ETF华安", "SH"),
    ("588050", "科创50ETF工银", "SH"),
    ("159922", "中证500ETF嘉实", "SZ"),       # 与 etf.jpg 不同：不在它列出的 19 只（第 2–20 行）中，见列表下方说明
    ("512500", "中证500ETF华夏", "SH"),
    ("560010", "中证1000ETF广发", "SH"),
    ("159845", "中证1000ETF华夏", "SZ"),
    ("515800", "中证800ETF汇添富", "SH"),
    ("159901", "深证100ETF易方达", "SZ"),
    ("159629", "中证1000ETF富国", "SZ"),
    ("510230", "金融ETF国泰", "SH"),
]
# The list shown in the reference video stops at 19 (its rows 2-20), but its charts include 159922 too:
# with it they match to the last digit shown (2026-01-28 −329.48亿份, 2026-11-03 +196.98亿份; on base
# 2025-11-20, 2026-06-12 30.07 and +0.06); without it they are 6.84亿份, 0.37亿份, 0.17 and 0.01 off.
SH = [c for c, _, x in FUNDS if x == "SH"]
SZ = [c for c, _, x in FUNDS if x == "SZ"]
NAMES = {c: n for c, n, _ in FUNDS}

START = "2025-10-09"          # the first trading day kept
BASE = "2025-11-20"           # the default base day: the reference charts' (a year before 2026-11-20)
UPPER = 70                    # 加仓指数 above it: the bottom is near (relatively close to the bottom)
LOWER = 30                    # below it: time to cut positions
RANGES = ("6m", "1y", "all")
RETRY_S = 30 * 60             # a day not published yet is asked for again after this
BASE_GAP = 7                  # a base day may fall back this many calendar days, to the trading day before
TOP_SHARE = 0.5               # the day's biggest movers shown: the top half of the funds by |change|

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
_tried: dict[tuple[str, str], float] = {}     # (exchange or code, day) -> when it came back without data
_lock = threading.Lock()
_sleep = time.sleep


def _path() -> Path:
    return store.root() / "web" / "etf_shares.parquet"


# --- the exchanges -------------------------------------------------------------------------------

def fetch_sse(day: str) -> dict[str, float]:
    """上交所: the funds' Shanghai ones on ``day`` (YYYY-MM-DD), in 份; {} when not published."""
    r = requests.get("https://query.sse.com.cn/commonQuery.do", timeout=20, params={
        "isPagination": "true", "pageHelp.pageSize": "10000", "pageHelp.pageNo": "1", "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1", "pageHelp.endPage": "1",
        "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L", "STAT_DATE": day,
    }, headers={"Referer": "https://www.sse.com.cn/", "User-Agent": _UA})
    r.raise_for_status()
    out = {}
    for row in r.json().get("result") or []:
        code = str(row.get("SEC_CODE"))
        if code in SH and row.get("TOT_VOL") not in (None, ""):
            out[code] = float(row["TOT_VOL"]) * 1e4          # 万份
    return out


def fetch_szse(code: str, start: str, end: str) -> dict[str, float]:
    """深交所: one fund's shares on each day from ``start`` to ``end``, in 份."""
    out: dict[str, float] = {}
    page = 1
    while True:
        r = requests.get("https://fund.szse.cn/api/report/ShowReport/data", timeout=20, params={
            "SHOWTYPE": "JSON", "CATALOGID": "fund_jjgm", "TABKEY": "tab1", "txtDm": code,
            "txtStart": start, "txtEnd": end, "PAGENO": page,
        }, headers={"Referer": "https://fund.szse.cn/marketdata/fundslist/index.html", "User-Agent": _UA})
        r.raise_for_status()
        table = r.json()[0]
        for row in table.get("data") or []:
            out[row["size_date"]] = float(str(row["current_size"]).replace(",", "")) * 1e4   # 万份
        if page >= int(table.get("metadata", {}).get("pagecount") or 0):
            return out
        page += 1


# --- the cache -----------------------------------------------------------------------------------

def _recent(key: tuple[str, str], now: float) -> bool:
    t = _tried.get(key)
    return t is not None and now - t < RETRY_S


def _retry(fn, *args, tries: int = 3, quiet: bool = True):
    """``fn(*args)``, tried again after 1 s and 2 s; on the last failure None (``quiet``) or the error."""
    for i in range(tries):
        try:
            return fn(*args)
        except Exception as e:                                  # noqa: BLE001 - logged, the disk is used
            if i == tries - 1:
                log.warning("ETF shares %s%s: %s", fn.__name__, args, e)
                if quiet:
                    return None
                raise
            _sleep(1 + i)


def update(days: list[str], *, fetch_sse=fetch_sse, fetch_szse=fetch_szse) -> tuple[pd.DataFrame, str, str | None]:
    """The shares on ``days`` (date × code, 份), only days with all the funds; with where they came from
    ("cache", "network" or "stale": an exchange failed, what is on disk is used) and a note."""
    path = _path()
    kept = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["date", "code", "shares"])
    have = set(zip(kept["date"], kept["code"], strict=True))
    now = time.time()
    rows: list[tuple[str, str, float]] = []
    errors: list[str] = []

    sh_days = [d for d in days if any((d, c) not in have for c in SH) and not _recent(("SH", d), now)]
    if sh_days:
        with ThreadPoolExecutor(4) as ex:
            for d, got in zip(sh_days, ex.map(lambda d: _retry(fetch_sse, d), sh_days), strict=True):
                if got is None:                                 # failed even after retries: next time
                    errors.append("上交所")
                    continue
                rows += [(d, c, v) for c, v in got.items()]
                if not set(SH) <= set(got):
                    _tried[("SH", d)] = now

    for code in SZ:
        need = [d for d in days if (d, code) not in have and not _recent((code, d), now)]
        if not need:
            continue
        try:
            for month in sorted({d[:7] for d in need}):
                first = pd.Timestamp(f"{month}-01")
                got = _retry(fetch_szse, code, f"{first:%Y-%m-%d}", f"{first + pd.offsets.MonthEnd(0):%Y-%m-%d}",
                             quiet=False)
                rows += [(d, code, v) for d, v in got.items() if d in days]
                for d in need:
                    if d[:7] == month and d not in got:
                        _tried[(code, d)] = now
        except Exception as e:                                  # noqa: BLE001
            log.warning("深交所 ETF shares (%s): %s", code, e)
            errors.append("深交所")
            break

    if rows:
        new = pd.DataFrame(rows, columns=["date", "code", "shares"])
        kept = (pd.concat([kept, new]) if len(kept) else new).drop_duplicates(["date", "code"], keep="last")
        kept = kept.sort_values(["date", "code"]).reset_index(drop=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        kept.to_parquet(path)

    part = kept[kept["date"].isin(days) & kept["code"].isin(NAMES)]
    wide = part.pivot(index="date", columns="code", values="shares").reindex(columns=list(NAMES)).sort_index()
    wide = wide.astype(float).round()           # whole 份: the exchanges publish 万份 to 2 places
    gaps = [d for d in days if d not in wide.index or wide.loc[d].isna().any()]
    wide = wide.dropna()

    notes = []
    if errors:
        notes.append(f"{'、'.join(dict.fromkeys(errors))}的份额暂时取不到，显示的是本地已有的数据")
    late = [d for d in gaps if not len(wide) or d > wide.index[-1]]
    if late:
        notes.append(f"{'、'.join(late[-3:])} 交易所尚未公布全部份额，暂不计入")
    source = "stale" if errors else ("network" if rows else "cache")
    return wide, source, "；".join(notes) or None


# --- size: shares × the day's close ----------------------------------------------------------------

def fetch_close(code: str) -> dict[str, float]:
    """新浪: one fund's daily closes since it listed (YYYY-MM-DD -> price), one request."""
    df = store.ak().fund_etf_hist_sina(symbol=("sh" if code in SH else "sz") + code)
    return dict(zip(pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"), pd.to_numeric(df["close"], errors="coerce"),
                    strict=True))


def _closes_path() -> Path:
    return store.root() / "web" / "etf_closes.parquet"


def closes(day: str) -> pd.DataFrame:
    """The funds' closes (date × code) to ``day``, from disk; a fund without ``day`` on disk is fetched
    again (at most every ``RETRY_S`` when the day is still missing). A fund that fails is left as it was."""
    path = _closes_path()
    kept = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["date", "code", "close"])
    have = set(zip(kept["date"], kept["code"], strict=True))
    now = time.time()
    rows: list[tuple[str, str, float]] = []
    for code in NAMES:
        if (day, code) in have or _recent(("close", code + day), now):
            continue
        got = _retry(fetch_close, code)
        if got is None:
            continue
        rows += [(d, code, v) for d, v in got.items() if d >= START and pd.notna(v)]
        if day not in got:
            _tried[("close", code + day)] = now
    if rows:
        new = pd.DataFrame(rows, columns=["date", "code", "close"])
        kept = (pd.concat([kept, new]) if len(kept) else new).drop_duplicates(["date", "code"], keep="last")
        kept = kept.sort_values(["date", "code"]).reset_index(drop=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        kept.to_parquet(path)
    part = kept[(kept["date"] <= day) & kept["code"].isin(NAMES)]
    return part.pivot(index="date", columns="code", values="close").sort_index().astype(float)


def sizes(day: str, wide: pd.DataFrame) -> pd.Series:
    """Each fund's size on ``day`` in 亿元 (its shares × the day's close, or the last close before it),
    largest first; a fund with no close is left out."""
    px = closes(day).ffill()
    if px.empty:
        return pd.Series(dtype=float)
    out = (wide.loc[day] * px.iloc[-1].reindex(wide.columns) / 1e8).dropna()
    return out.sort_values(ascending=False)


# --- the series ----------------------------------------------------------------------------------

def compute(wide: pd.DataFrame, base: str) -> pd.DataFrame:
    """Per day: ``total`` and ``change`` (亿份), ``index`` (base day = 100) and
    ``index_change`` (against the day before), ``rate5`` / ``rate20``."""
    if wide.empty:
        raise ValueError("no shares")
    total = wide.sum(axis=1) / 1e8
    on = total.index[total.index <= base]
    if not len(on):
        raise ValueError(f"基期须不早于 {total.index[0]}")
    if pd.Timestamp(base) - pd.Timestamp(on[-1]) > pd.Timedelta(days=BASE_GAP):
        raise ValueError(f"基期 {base} 前后没有份额数据（最近的是 {on[-1]}），请稍后再试或换一个基期")
    index = 100 * total / total[on[-1]]
    out = pd.DataFrame({"date": total.index, "total": total.values, "change": total.diff().values,
                        "index": index.values, "index_change": index.diff().values,
                        "rate5": index.diff(5).values,
                        "rate20": index.diff(20).values})
    out.attrs["base"] = on[-1]
    return out


def _trade_days() -> list[str]:
    last = pd.Timestamp(store.last_closed_trade_date())
    return [f"{d:%Y-%m-%d}" for d in store.trade_calendar() if pd.Timestamp(START) <= d <= last]


def round_half_even(v, nd: int = 2) -> float | None:
    """``v`` to ``nd`` places, an exact half to the even digit, as the reference charts round
    (−329.475 → −329.48, 196.985 → 196.98). The float's own noise (−329.47499999999997) is cleared
    first, so a value that is a half in 份 is treated as one."""
    if v is None or pd.isna(v):
        return None
    exact = Decimal(repr(round(float(v), 10)))
    return float(exact.quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_EVEN))


_num = round_half_even


def broad(base: str | None = None, rng: str = "1y") -> dict:
    """The page: the funds' series over ``rng`` (6m, 1y, all) against ``base``, and each fund."""
    if rng not in RANGES:
        raise ValueError(f"range must be one of {', '.join(RANGES)}")
    with _lock:
        wide, source, note = update(_trade_days(), fetch_sse=fetch_sse, fetch_szse=fetch_szse)
    if wide.empty:
        raise FileNotFoundError("宽基ETF份额还没有下载到")
    series = compute(wide, base or BASE)
    base_day = series.attrs["base"]
    as_of = wide.index[-1]

    start = wide.index[0]
    if rng != "all":
        start = f"{pd.Timestamp(as_of) - pd.DateOffset(months=6 if rng == '6m' else 12):%Y-%m-%d}"
    diff = wide.diff() / 1e8
    days = []
    for r in series[series["date"] >= start].itertuples(index=False):
        d = diff.loc[r.date].dropna()
        moved = d.abs().sum()
        top = d.reindex(d.abs().sort_values(ascending=False).index[:math.ceil(len(d) * TOP_SHARE)])
        days.append({"date": r.date, "total": _num(r.total), "change": _num(r.change), "index": _num(r.index),
                     "index_change": _num(r.index_change),
                     "rate5": _num(r.rate5), "rate20": _num(r.rate20),
                     # [code, change in 亿份, its share of the day's whole movement Σ|change| in %]
                     "top": [[c, _num(v), _num(abs(v) / moved * 100) if moved else None] for c, v in top.items()]})

    last, first = wide.loc[as_of], wide.loc[base_day]
    try:
        size = sizes(as_of, wide)
    except Exception as e:                                      # noqa: BLE001 - the index stands without it
        log.warning("ETF sizes: %s", e)
        size = pd.Series(dtype=float)
    if size.empty:
        note = "；".join(x for x in (note, "规模暂缺（取不到收盘价）") if x)
    funds = [{"code": c, "name": n, "exchange": x,
              "size": _num(size.get(c)),
              "shares": _num(last[c] / 1e8, 4),
              "day": _num(diff.loc[as_of, c], 4),
              "since_base": _num((last[c] - first[c]) / 1e8, 4),
              "since_base_pct": _num(100 * (last[c] / first[c] - 1)),
              "weight": _num(100 * first[c] / first.sum(), 4)}
             for c, n, x in FUNDS]
    funds.sort(key=lambda f: (f["size"] is None, -(f["size"] or 0), -f["weight"]))   # the day's size, largest first
    return {"base": base_day, "base_total": _num(first.sum() / 1e8), "range": rng, "start": start, "as_of": as_of, "source": source, "note": note,
            "funds": funds, "days": days}
