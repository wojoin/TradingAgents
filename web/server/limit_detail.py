"""What the day's limit-up stocks' own price data does not tell: why each one hit the limit
(涨停原因), when it first and last sealed it, and the buy orders left at the limit at the close
(封单量, 封单额); for the limit-down ones, when they first and last sealed the lower limit.

同花顺's limit-up pool (the JSON behind data.10jqka.com.cn, not a published API) has all of it
and goes back years, but leaves out the Beijing exchange; Eastmoney's pool fills those in with
the times and the order amount, for the last month or so only. A closed day's result is kept on
disk (``.akshare_data/web/limit_detail``); a day neither source serves is retried after a while.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from tradingagents.dataflows.vendors.akshare import store

log = logging.getLogger(__name__)

COLUMNS = ["code", "reason", "first_time", "last_time", "order_volume", "order_amount", "source"]
THS_URL = "https://data.10jqka.com.cn/dataapi/limit_up/"
# Per side: the pool's path, its fields and what its times are called.
_THS = {
    "up": ("limit_up_pool", "199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004",
           "330324", "limit_up"),
    "down": ("lower_limit_pool", "199112,10,9001,330333,330334,330335,9002,330329,133971,133970,1968584,3475914,9003,9004",
             "330334", "limit_down"),
}
_EM = {"up": ("stock_zt_pool_em", "封板资金"), "down": ("stock_zt_pool_dtgc_em", "封单资金")}
_PAGE = 200
_RETRY_AFTER = 600            # seconds before asking again for a day that failed
_CST = ZoneInfo("Asia/Shanghai")

_lock = threading.Lock()
_failed: dict[tuple[str, str], float] = {}


def _cache(day: str, side: str = "up") -> Path:
    name = day.replace("-", "") if side == "up" else f"down_{day.replace('-', '')}"
    return store.root() / "web" / "limit_detail" / f"{name}.parquet"


def _clock(ts) -> str | None:
    """A unix time (同花顺) as HH:MM:SS in China time."""
    try:
        return datetime.fromtimestamp(int(ts), _CST).strftime("%H:%M:%S")
    except (TypeError, ValueError, OverflowError):
        return None


def _hhmmss(v) -> str | None:
    """Eastmoney's 092500 as 09:25:00."""
    s = str(v or "").strip()
    if not s.isdigit():
        return None
    s = s.zfill(6)
    return f"{s[:2]}:{s[2:4]}:{s[4:6]}"


def fetch_ths(day: str, get=requests.get, side: str = "up") -> pd.DataFrame:
    """同花顺's limit-up (or limit-down) pool for ``day`` (YYYY-MM-DD), every page."""
    path, fields, order, t = _THS[side]
    rows, page = [], 1
    while True:
        r = get(THS_URL + path, params={"page": page, "limit": _PAGE, "field": fields, "filter": "HS,GEM2STAR",
                                        "order_field": order, "order_type": "0", "date": day.replace("-", "")},
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.10jqka.com.cn/"}, timeout=15)
        r.raise_for_status()
        body = r.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not data:
            raise ValueError(f"同花顺 limit-up pool: {body.get('status_msg') if isinstance(body, dict) else body}")
        info = data.get("info") or []
        rows += [{"code": str(i.get("code", "")).zfill(6), "reason": i.get("reason_type") or None,
                  "first_time": _clock(i.get(f"first_{t}_time")), "last_time": _clock(i.get(f"last_{t}_time")),
                  "order_volume": i.get("order_volume"), "order_amount": i.get("order_amount"), "source": "ths"}
                 for i in info]
        total = int((data.get("page") or {}).get("total") or 0)
        if not info or len(rows) >= total:
            break
        page += 1
    return pd.DataFrame(rows, columns=COLUMNS)


def fetch_em(day: str, side: str = "up") -> pd.DataFrame:
    """Eastmoney's limit-up (or limit-down) pool for ``day``: the times and the order amount;
    the order volume is that over the closing price, as Eastmoney has no column for it. Its
    limit-down pool has the last sealing time only."""
    fn, amount_col = _EM[side]
    df = getattr(store.ak(), fn)(date=day.replace("-", ""))
    if df is None or not len(df):
        return pd.DataFrame(columns=COLUMNS)
    amount = pd.to_numeric(df[amount_col], errors="coerce")
    first = df["首次封板时间"].map(_hhmmss) if "首次封板时间" in df else None
    price = pd.to_numeric(df["最新价"], errors="coerce")
    return pd.DataFrame({
        "code": df["代码"].astype(str).str.zfill(6), "reason": None,
        "first_time": first, "last_time": df["最后封板时间"].map(_hhmmss),
        "order_volume": (amount / price).where(price > 0).round(), "order_amount": amount, "source": "em",
    }, columns=COLUMNS)


def _closed(day: str) -> bool:
    now = datetime.now(_CST)
    return day < now.strftime("%Y-%m-%d") or (day == now.strftime("%Y-%m-%d") and now.hour * 60 + now.minute >= 15 * 60 + 30)


def details(day: str, ths=None, em=None, side: str = "up") -> pd.DataFrame:
    """code -> reason, first and last sealing time, order volume and amount on ``day`` for the
    limit-ups (``side="down"``: the limit-downs); empty when neither source serves it."""
    ths = ths or (lambda d: fetch_ths(d, side=side))
    em = em or (lambda d: fetch_em(d, side=side))
    path, key = _cache(day, side), (side, day)
    if path.exists():
        return pd.read_parquet(path)
    with _lock:
        if time.time() - _failed.get(key, 0) < _RETRY_AFTER:
            return pd.DataFrame(columns=COLUMNS)
        parts, ok = [], False
        for name, fn in (("同花顺", ths), ("Eastmoney", em)):
            try:
                parts.append(fn(day))
                ok = True
            except Exception as e:  # noqa: BLE001 — a feed that is down or no longer keeps the day
                log.info("limit-%s details from %s for %s: %s", side, name, day, e)
        if not ok:
            _failed[key] = time.time()
            return pd.DataFrame(columns=COLUMNS)
        # 同花顺 first; Eastmoney only for the stocks 同花顺 leaves out (the Beijing exchange).
        out = pd.concat([p for p in parts if len(p)], ignore_index=True) if any(len(p) for p in parts) \
            else pd.DataFrame(columns=COLUMNS)
        out = out.drop_duplicates("code", keep="first").reset_index(drop=True)
        _failed.pop(key, None)
        # Keep a closed day only when 同花顺 answered: Eastmoney alone has no reasons nor,
        # for the limit-downs, first times.
        if _closed(day) and len(out) and (out["source"] == "ths").any():
            path.parent.mkdir(parents=True, exist_ok=True)
            out.to_parquet(path)
        return out
