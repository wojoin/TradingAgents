"""五日分时: the last few trading days of an A-share minute by minute, for the stock page's 五日 chart.

Sina's 1-minute bars through AKShare (``stock_zh_a_minute``: about the last 8 trading days, unadjusted).
Each minute's price is its close; the 均价 line is the day's running amount ÷ volume; the change is
against the close of the day before the first day shown. Kept in memory for a minute so the page
does not ask the source on every view.
"""
from __future__ import annotations

import threading
import time

import pandas as pd

from tradingagents.dataflows.symbols import a_share_code, exchange_prefix

TTL = 60
_cache: dict[tuple[str, int], tuple[float, dict]] = {}
_lock = threading.Lock()


def _fetch(symbol: str) -> pd.DataFrame:
    import akshare as ak
    return ak.stock_zh_a_minute(symbol=symbol, period="1", adjust="")


def intraday(code: str, days: int = 5, fetch=None) -> dict:
    c = a_share_code(code)
    ex = exchange_prefix(c) if c else None
    if not ex:
        raise LookupError(f"{code} is not an A-share stock")
    key = (c, days)
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < TTL and fetch is None:
            return hit[1]
    df = (fetch or _fetch)(f"{ex.lower()}{c}")
    if df is None or df.empty:
        raise LookupError(f"no minute data for {c}")
    df = df.copy()
    df["day"] = df["day"].astype(str)
    df["date"] = df["day"].str[:10]
    for col in ("open", "high", "low", "close", "volume", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    all_days = sorted(df["date"].unique())
    shown = all_days[-days:]
    before = all_days[:-days]
    prev_close = float(df[df["date"] == before[-1]]["close"].iloc[-1]) if before else None
    df = df[df["date"].isin(shown)]
    if prev_close is None:                                  # no earlier day fetched: the first minute's open
        prev_close = float(df["open"].iloc[0])
    out_days = []
    for d in shown:
        g = df[df["date"] == d]
        vol, amt = g["volume"].cumsum(), g["amount"].cumsum()
        avg = (amt / vol).where(vol > 0)
        out_days.append({"date": d, "close": float(g["close"].iloc[-1]),
                         "points": [{"time": t[11:16], "price": float(p), "avg": None if pd.isna(a) else round(float(a), 3),
                                     "volume": float(v), "amount": float(m)}
                                    for t, p, a, v, m in zip(g["day"], g["close"], avg, g["volume"], g["amount"], strict=True)]})
    res = {"symbol": c, "prev_close": prev_close, "days": out_days, "source": "新浪财经 1 分钟（不复权）",
           "volume_unit": "股"}
    with _lock:
        _cache[key] = (time.time(), res)
    return res


# ---------------------------------------------------------------------------
# 分时 extras: the opening call auction (集合竞价) and the trade-by-trade list (成交明细)
# ---------------------------------------------------------------------------
EM_COOLDOWN = 600            # seconds without asking Eastmoney after it rate-limits this IP
_em_blocked_until = 0.0
TICK_TTL = 120               # today's trades, kept in memory this long (a closed day: on disk for good)
_tick_cache: dict[tuple[str, str], tuple[float, dict]] = {}


def _em(fn):
    """Call an Eastmoney feed unless it rate-limited us lately; a rate limit pauses it for EM_COOLDOWN."""
    global _em_blocked_until
    if time.time() < _em_blocked_until:
        raise RuntimeError("东方财富限流中，暂不请求")
    try:
        return fn()
    except Exception as e:
        if "RateLimit" in type(e).__name__ or "限流" in str(e):
            _em_blocked_until = time.time() + EM_COOLDOWN
        raise


def _quiet(fn):
    """AKShare's page-by-page feeds draw a progress bar: off while they run."""
    import os
    prev = os.environ.get("TQDM_DISABLE")
    os.environ["TQDM_DISABLE"] = "1"
    try:
        return fn()
    finally:
        if prev is None:
            os.environ.pop("TQDM_DISABLE", None)
        else:
            os.environ["TQDM_DISABLE"] = prev


def _tick_dir():
    from tradingagents.dataflows.vendors.akshare import store
    return store.root() / "web" / "ticks"


def _day_closed(day: str) -> bool:
    from tradingagents.dataflows.vendors.akshare import store
    return pd.Timestamp(day).date() < store.now_cst().date() or not store.is_intraday()


SIDE = {"U": "买", "D": "卖", "E": "中性", "买盘": "买", "卖盘": "卖", "中性盘": "中性"}


def _ticks_em(code: str) -> pd.DataFrame:
    import akshare as ak
    df = _em(lambda: ak.stock_intraday_em(symbol=code))
    cols = {c: c for c in df.columns}
    t = next(c for c in cols if "时间" in c)
    p = next(c for c in cols if "价" in c)
    v = next(c for c in cols if "手" in c or "量" in c)
    s = next((c for c in cols if "性质" in c or "方向" in c), None)
    return pd.DataFrame({"time": df[t].astype(str).str[:8], "price": pd.to_numeric(df[p], errors="coerce"),
                         "volume": pd.to_numeric(df[v], errors="coerce") * 100,      # 手 → 股
                         "side": df[s].map(lambda x: SIDE.get(str(x), str(x))) if s else "中性"})


def _ticks_sina(code: str, day: str) -> pd.DataFrame:
    import akshare as ak
    ex = exchange_prefix(code).lower()
    df = _quiet(lambda: ak.stock_intraday_sina(symbol=f"{ex}{code}", date=day.replace("-", "")))
    return pd.DataFrame({"time": df["ticktime"].astype(str), "price": pd.to_numeric(df["price"], errors="coerce"),
                         "volume": pd.to_numeric(df["volume"], errors="coerce"),
                         "side": df["kind"].map(lambda x: SIDE.get(str(x), "中性"))})


def ticks(code: str, day: str | None = None, em=None, sina=None) -> dict:
    """The day's trades (成交明细) as the free feeds give them: 3-second snapshots, each row the trades
    of those 3 seconds added up (not single orders; another vendor's snapshots fall on other seconds,
    so rows differ while the day's total agrees): time, price, shares, side (主动买 / 卖 / 中性); the
    09:25 call-auction match and the 15:00 close included. Eastmoney first (one request), Sina's
    trade list when Eastmoney is unavailable (slower: page by page). A closed day is kept on disk."""
    c = a_share_code(code)
    if not c or not exchange_prefix(c):
        raise LookupError(f"{code} is not an A-share stock")
    if day is None:
        day = intraday(c, 1)["days"][-1]["date"]
    key = (c, day)
    path = _tick_dir() / f"{c}_{day}.parquet"
    if path.exists():
        df = pd.read_parquet(path)
        src = f"{df['src'].iloc[0]}（本地缓存）" if "src" in df and len(df) else "本地缓存"
        df = df.drop(columns=["src"], errors="ignore")
    else:
        with _lock:
            hit = _tick_cache.get(key)
            if hit and time.time() - hit[0] < TICK_TTL and em is None and sina is None:
                return hit[1]
        errors = []
        df, src = None, None
        from tradingagents.dataflows.vendors.akshare import store
        today = pd.Timestamp(day).date() >= store.now_cst().date()
        if today:                                    # Eastmoney's list is today's only
            try:
                df, src = (em or _ticks_em)(c), "东方财富分笔"
            except Exception as e:  # noqa: BLE001
                errors.append(f"东方财富：{type(e).__name__}")
        if df is None:
            try:
                df, src = (sina or _ticks_sina)(c, day), "新浪 3 秒分笔快照"
            except Exception as e:  # noqa: BLE001
                errors.append(f"新浪：{type(e).__name__}")
        if df is None or df.empty:
            raise RuntimeError("成交明细暂不可用（" + "；".join(errors or ["没有数据"]) + "）")
        df = df.dropna(subset=["price"]).sort_values("time", kind="stable").reset_index(drop=True)
        if _day_closed(day):
            path.parent.mkdir(parents=True, exist_ok=True)
            df.assign(src=src).to_parquet(path, index=False)      # the source kept with the trades
    # The opening (09:25) and closing (15:00) call auctions match buyers and sellers at one price:
    # no side is active, whatever the feed marks, so they are 竞价 and count as neither buying nor selling.
    is_auction = (df["time"] <= "09:25:59") | (df["time"] >= "15:00:00")
    df = df.assign(side=df["side"].where(~is_auction, "竞价"))
    auction = df[df["time"] <= "09:25:59"]
    buy = df.loc[df["side"] == "买", "volume"].sum()
    sell = df.loc[df["side"] == "卖", "volume"].sum()
    res = {"symbol": c, "date": day, "source": src, "volume_unit": "股", "count": len(df),
           "buy_volume": float(buy), "sell_volume": float(sell),
           "auction_volume": float(df.loc[is_auction, "volume"].sum()), "auction_count": int(is_auction.sum()),
           "auction": None if auction.empty else {"time": auction["time"].iloc[-1], "price": float(auction["price"].iloc[-1]),
                                                  "volume": float(auction["volume"].iloc[-1])},
           "rows": [{"time": t, "price": float(p), "volume": float(v), "side": s}
                    for t, p, v, s in zip(df["time"], df["price"], df["volume"], df["side"], strict=True)]}
    with _lock:
        _tick_cache[key] = (time.time(), res)
    return res


def _auction_path(code: str, day: str):
    return _tick_dir().parent / "auction" / f"{code}_{day}.parquet"


def _auction_final(day: str) -> bool:
    """The day's auction is over (09:25 passed, or a later day): its minutes can be kept for good."""
    from tradingagents.dataflows.vendors.akshare import store
    now = store.now_cst()
    return pd.Timestamp(day).date() < now.date() or now.strftime("%H:%M") >= "09:26"


def _with_match(c: str, res: dict) -> dict:
    """The auction's 09:25 point from the trades: the real opening match (price and shares), not
    Eastmoney's last indicative price before it; its earlier minutes carry no trade (volume 0)."""
    try:
        m = ticks(c, res["date"])["auction"]
    except Exception:  # noqa: BLE001 - the indicative 09:25 stands
        m = None
    if m and res["points"]:
        pts = [p for p in res["points"] if p["time"] < "09:25"]
        pts.append({"time": "09:25", "price": m["price"], "volume": m["volume"]})
        res = {**res, "points": pts, "match": {"time": "09:25", "price": m["price"], "volume": m["volume"]}}
    return res


def auction(code: str, em=None, day: str | None = None) -> dict:
    """The opening call auction (集合竞价, 09:15–09:25): each minute's indicative matching price from
    Eastmoney (no trades then, so no volume), ending on the real 09:25 match from the trade list. From
    Eastmoney (its
    pre-market minutes, which it serves for today only, so a finished day is kept on disk under
    web/auction/); when Eastmoney is unavailable and nothing is kept, only the 09:25 match from
    the trade list."""
    c = a_share_code(code)
    if not c or not exchange_prefix(c):
        raise LookupError(f"{code} is not an A-share stock")
    if day is None:
        try:
            day = intraday(c, 1)["days"][-1]["date"]
        except Exception:  # noqa: BLE001 - only to find a kept day
            day = None
    if day and _auction_path(c, day).exists():
        kept = pd.read_parquet(_auction_path(c, day))
        pts = [{"time": t, "price": float(p), "volume": float(v)} for t, p, v in zip(kept["time"], kept["price"], kept["volume"], strict=True)]
        return _with_match(c, {"symbol": c, "date": day, "source": "东方财富盘前分时（本地保存）", "points": pts,
                                "match": {"time": "09:25", "price": pts[-1]["price"], "volume": pts[-1]["volume"]}})
    try:
        import akshare as ak
        df = (em or (lambda s: _em(lambda: ak.stock_zh_a_hist_pre_min_em(symbol=s, start_time="09:15:00",
                                                                         end_time="09:30:00"))))(c)
        t = next(x for x in df.columns if "时间" in x)
        p = next(x for x in df.columns if x in ("最新价", "收盘"))
        v = next(x for x in df.columns if "成交量" in x)
        df = df.assign(_t=df[t].astype(str))
        day = df["_t"].str[:10].max()
        df = df[(df["_t"].str[:10] == day) & (df["_t"].str[11:16] >= "09:15") & (df["_t"].str[11:16] <= "09:25")]
        pts = [{"time": x[11:16], "price": float(pr), "volume": float(vo) * 100}
               for x, pr, vo in zip(df["_t"], pd.to_numeric(df[p], errors="coerce"),
                                    pd.to_numeric(df[v], errors="coerce").fillna(0), strict=True) if pr == pr]
        if pts:
            if _auction_final(day) and pts[-1]["time"] >= "09:25":
                path = _auction_path(c, day)
                path.parent.mkdir(parents=True, exist_ok=True)
                pd.DataFrame(pts).to_parquet(path, index=False)
            return _with_match(c, {"symbol": c, "date": day, "source": "东方财富（盘前分时）", "points": pts,
                                    "match": {"time": "09:25", "price": pts[-1]["price"], "volume": pts[-1]["volume"]}})
    except Exception as e:  # noqa: BLE001 - the trade list's 09:25 match stands in
        reason = type(e).__name__
    else:
        reason = "没有盘前数据"
    t = ticks(c)
    return {"symbol": c, "date": t["date"], "source": f"新浪逐笔（东方财富盘前分时不可用：{reason}）", "points": [],
            "match": t["auction"]}
