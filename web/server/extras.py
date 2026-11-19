"""More market figures for the 行情 stats:

  margin   两融余额 (margin financing plus securities lending) on the Shanghai and Shenzhen
           exchanges each trading day since 2010: the long history from the data sync's
           ``margin_sh`` / ``margin_sz`` (macro_china_market_margin_*, about a week behind),
           topped up with the days since from the exchanges themselves (上交所 by range,
           深交所 a day at a time). The exchanges publish a day's figures the next morning.
  bond     China's 10-year government bond yield since 2005 (the data sync's ``ts/bond``).
  themes   the day's limit-up themes: 同花顺's 涨停原因 split at "+", counted over the last few
           trading days, the most limit-ups today first.

Each series is brought up to date at most once per closed trading day.
"""
from __future__ import annotations

import logging
import threading
from collections import Counter

import pandas as pd

from tradingagents.dataflows.vendors.akshare import settings as ak_settings, store
from web.server import limit_detail, market

log = logging.getLogger(__name__)
THEME_DAYS = (3, 5, 10)
_lock = threading.Lock()
_MEMO: dict[tuple[str, str], tuple[pd.DataFrame, str | None]] = {}


def _memo(name: str, build) -> tuple[pd.DataFrame, str | None]:
    key = (name, market.last_closed_day())
    with _lock:
        if key not in _MEMO:
            for k in [k for k in _MEMO if k[0] == name]:
                del _MEMO[k]
            _MEMO[key] = build()
        return _MEMO[key]


# ---------------------------------------------------------------------------
# 两融余额
# ---------------------------------------------------------------------------
_MARGIN_COLS = ["date", "total", "fin", "fin_buy"]


def _margin_history(name: str) -> pd.DataFrame:
    fn = getattr(store.ak(), f"macro_china_market_margin_{name[-2:]}")
    df = store.cached(name, fn, "daily")
    return pd.DataFrame({"date": store.to_local_dates(df["日期"]).dt.strftime("%Y-%m-%d"),
                         "total": pd.to_numeric(df["融资融券余额"], errors="coerce"),
                         "fin": pd.to_numeric(df["融资余额"], errors="coerce"),
                         "fin_buy": pd.to_numeric(df["融资买入额"], errors="coerce")})


def _sse_since(start: str, end: str) -> pd.DataFrame:
    df = store.ak().stock_margin_sse(start_date=start.replace("-", ""), end_date=end.replace("-", ""))
    if df is None or not len(df):
        return pd.DataFrame(columns=_MARGIN_COLS)
    return pd.DataFrame({"date": pd.to_datetime(df["信用交易日期"].astype(str)).dt.strftime("%Y-%m-%d"),
                         "total": pd.to_numeric(df["融资融券余额"], errors="coerce"),
                         "fin": pd.to_numeric(df["融资余额"], errors="coerce"),
                         "fin_buy": pd.to_numeric(df["融资买入额"], errors="coerce")})


def _szse_day(day: str) -> pd.DataFrame:
    """深交所 for one day (in 亿元); empty when not published yet."""
    try:
        df = store.ak().stock_margin_szse(date=day.replace("-", ""))
    except Exception:  # noqa: BLE001 — a day not published yet makes akshare fail on an empty table
        return pd.DataFrame(columns=_MARGIN_COLS)
    if df is None or not len(df):
        return pd.DataFrame(columns=_MARGIN_COLS)
    r = df.iloc[0]
    return pd.DataFrame([{"date": day, "total": float(r["融资融券余额"]) * 1e8, "fin": float(r["融资余额"]) * 1e8,
                          "fin_buy": float(r["融资买入额"]) * 1e8}])


def _build_margin(history=_margin_history, sse=_sse_since, szse=_szse_day) -> tuple[pd.DataFrame, str | None]:
    note = None
    parts = {}
    for ex in ("margin_sh", "margin_sz"):
        try:
            parts[ex] = history(ex)
        except Exception as e:  # noqa: BLE001
            parts[ex] = pd.DataFrame(columns=_MARGIN_COLS)
            note = f"两融历史数据不可得：{type(e).__name__}"
    # The days since the long history ends, from the exchanges.
    last_closed = market.last_closed_day()
    days = [d for d in market.trading_days() if d <= last_closed]
    for ex in ("margin_sh", "margin_sz"):
        h = parts[ex]
        since = h["date"].max() if len(h) else None
        todo = [d for d in days if since is None or d > since][-30:]
        if not todo:
            continue
        try:
            fresh = sse(todo[0], todo[-1]) if ex == "margin_sh" else pd.concat(
                [szse(d) for d in todo], ignore_index=True)
        except Exception as e:  # noqa: BLE001 — the history alone, then
            log.info("margin top-up for %s: %s", ex, e)
            note = note or f"两融最近几日未能更新：{type(e).__name__}"
            continue
        parts[ex] = pd.concat([h, fresh], ignore_index=True).drop_duplicates("date", keep="last")
    sh, sz = parts["margin_sh"].set_index("date"), parts["margin_sz"].set_index("date")
    both = sh.join(sz, lsuffix="_sh", rsuffix="_sz", how="inner").sort_index()   # a day both report
    out = pd.DataFrame({
        "date": both.index, "total": (both["total_sh"] + both["total_sz"]).to_numpy(),
        "fin": (both["fin_sh"] + both["fin_sz"]).to_numpy(), "fin_buy": (both["fin_buy_sh"] + both["fin_buy_sz"]).to_numpy(),
        "sh": both["total_sh"].to_numpy(), "sz": both["total_sz"].to_numpy(),
    }).dropna(subset=["total"]).reset_index(drop=True)
    return out, note


def margin(end: str | None = None, rng: str = "1y", build=None) -> dict:
    """两融余额 each trading day in ``rng`` ending on ``end`` (or the last day published before it)."""
    if rng not in market.STATS_RANGES:
        raise ValueError(f"range must be one of {', '.join(market.STATS_RANGES)}")
    df, note = _memo("margin", build or _build_margin)
    if end:
        df = df[df["date"] <= end]
    if df.empty:
        raise FileNotFoundError(f"no margin data on or before {end}")
    dates = df["date"].tolist()
    start = market._range_start(dates[-1], rng, dates)
    part = df[df["date"] >= start]
    prev = df["total"].shift(1)
    chg = (df["total"] - prev).loc[part.index]

    def r(v):
        return None if pd.isna(v) else round(float(v))
    return {"range": rng, "start": start, "as_of": dates[-1], "note": note,
            "days": [{"date": d, "total": r(t), "fin": r(f), "fin_buy": r(b), "sh": r(a), "sz": r(z), "chg": r(c)}
                     for d, t, f, b, a, z, c in zip(part["date"], part["total"], part["fin"], part["fin_buy"],
                                                    part["sh"], part["sz"], chg, strict=False)]}


# ---------------------------------------------------------------------------
# 10-year government bond yield
# ---------------------------------------------------------------------------
def _fetch_bond() -> pd.DataFrame:
    return store.incremental("bond", lambda s: store.ak().bond_zh_us_rate(start_date=s), "日期", ak_settings.START_DATE)


def bond10(fetch=None) -> tuple[pd.Series, str | None]:
    """date -> China's 10-year yield (%), and a note when it could not be brought up to date."""
    def build():
        note = None
        try:
            df = (fetch or _fetch_bond)()
            if "bond" in store.FALLBACKS:
                note = f"国债收益率未能更新：{store.FALLBACKS.pop('bond')}"
        except Exception as e:  # noqa: BLE001
            path = store.ts_path("bond")
            if not path.exists():
                return pd.DataFrame({"date": [], "y10": []}), f"国债收益率不可得：{type(e).__name__}"
            df, note = pd.read_parquet(path), f"国债收益率未能更新，使用本地数据：{type(e).__name__}"
        out = pd.DataFrame({"date": store.to_local_dates(df["日期"]).dt.strftime("%Y-%m-%d"),
                            "y10": pd.to_numeric(df["中国国债收益率10年"], errors="coerce")}).dropna()
        return out.drop_duplicates("date", keep="last").sort_values("date"), note
    df, note = _memo("bond", build)
    return df.set_index("date")["y10"], note


# ---------------------------------------------------------------------------
# 涨停题材
# ---------------------------------------------------------------------------
def split_reason(reason) -> list[str]:
    """同花顺's 涨停原因 ("MicroLED+AI眼镜+像素车灯") as its themes."""
    if not isinstance(reason, str):
        return []
    return [t.strip() for t in reason.replace("＋", "+").split("+") if t.strip()]


def themes(date: str | None = None, days: int = 5, top: int = 15, details=None) -> dict:
    """The themes of the day's limit-ups, counted on each of the last ``days`` trading days."""
    if days not in THEME_DAYS:
        raise ValueError(f"days must be one of {', '.join(map(str, THEME_DAYS))}")
    details = details or limit_detail.details
    span = market._days_on_record(date)[-days:]
    day = span[-1]
    names = market._names().set_index("code")["name"]
    per_day: dict[str, Counter] = {}
    stocks: dict[str, list[dict]] = {}
    have = []
    for d in span:
        det = details(d)
        if det is None or not len(det) or "reason" not in det or det["reason"].isna().all():
            per_day[d] = Counter()
            continue
        have.append(d)
        c = Counter()
        for code, reason in zip(det["code"], det["reason"], strict=False):
            for t in set(split_reason(reason)):
                c[t] += 1
                if d == day:
                    stocks.setdefault(t, []).append({"code": code, "name": names.get(code, code)})
        per_day[d] = c
    today = per_day[day]
    every = Counter()
    for c in per_day.values():
        every.update(c)
    picked = sorted(every, key=lambda t: (-today.get(t, 0), -every[t], t))[:top]
    out = [{"name": t, "today": today.get(t, 0), "counts": [per_day[d].get(t, 0) for d in span], "total": every[t],
            "days_on": sum(1 for d in span if per_day[d].get(t, 0)), "stocks": stocks.get(t, [])} for t in picked]
    return {"date": day, "dates": span, "have": have, "themes": out}


def invalidate() -> None:
    with _lock:
        _MEMO.clear()


# ---------------------------------------------------------------------------
# 市场波动率: the 50ETF option volatility index (QVIX), China's VIX
# ---------------------------------------------------------------------------
def _range_part(df: pd.DataFrame, end: str | None, rng: str) -> tuple[pd.DataFrame, str]:
    if rng not in market.STATS_RANGES:
        raise ValueError(f"range must be one of {', '.join(market.STATS_RANGES)}")
    if end:
        df = df[df["date"] <= end]
    if df.empty:
        raise FileNotFoundError(f"no data on or before {end}")
    dates = df["date"].tolist()
    start = market._range_start(dates[-1], rng, dates)
    return df[df["date"] >= start], start


def _r(v, d: int = 2):
    return None if v is None or pd.isna(v) else round(float(v), d)


def qvix(end: str | None = None, rng: str = "1y", fetch=None) -> dict:
    """QVIX each trading day in ``rng``, with where the last close sits since 2015."""
    def build():
        df = store.cached("qvix", fetch or store.ak().index_option_50etf_qvix, "daily")
        out = pd.DataFrame({"date": pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"),
                            "close": pd.to_numeric(df["close"], errors="coerce"),
                            "high": pd.to_numeric(df["high"], errors="coerce")}).dropna(subset=["close"])
        return out.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True), None
    df, _ = _memo("qvix", build)
    part, start = _range_part(df, end, rng)
    hist = df[df["date"] <= part["date"].iat[-1]]["close"]
    last = float(part["close"].iat[-1])
    return {"range": rng, "start": start, "as_of": part["date"].iat[-1], "since": df["date"].iat[0],
            "rank": _r((hist <= last).mean() * 100, 1), "median": _r(hist.median()),
            "days": [{"date": d, "close": _r(c), "high": _r(h)} for d, c, h in zip(part["date"], part["close"], part["high"], strict=False)]}


# ---------------------------------------------------------------------------
# 资金流向: the whole market's main-force flow (Eastmoney, the last 120 trading days) and the
# industries' over 1, 5 or 10 days (Eastmoney's per-stock rankings summed by 申万 industry)
# ---------------------------------------------------------------------------
_FLOW_COLS = {"main": "主力净流入-净额", "super": "超大单净流入-净额", "large": "大单净流入-净额",
              "mid": "中单净流入-净额", "small": "小单净流入-净额", "main_pct": "主力净流入-净占比"}
FLOW_SPANS = ("1d", "5d", "10d")


def market_flow(end: str | None = None, rng: str = "60d", fetch=None) -> dict:
    def build():
        df = store.cached("market_fund_flow", fetch or store.ak().stock_market_fund_flow, "daily")
        out = pd.DataFrame({"date": pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d"),
                            **{k: pd.to_numeric(df[c], errors="coerce") for k, c in _FLOW_COLS.items()}})
        return out.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True), None
    df, _ = _memo("market_flow", build)
    part, start = _range_part(df, end, rng)
    return {"range": rng, "start": start, "as_of": part["date"].iat[-1], "first": df["date"].iat[0],
            "days": [{"date": r["date"], **{k: _r(r[k], 2 if k == "main_pct" else 0) for k in _FLOW_COLS}}
                     for r in part.to_dict("records")]}


THS_NOTE = "同花顺口径：按主动买卖方向统计全部成交，不分主力，数值不能与东方财富主力净流入比较"
_THS_SPANS = {"1d": ("即时", "now", "净额"), "5d": ("5日排行", "5d", "资金流入净额"), "10d": ("10日排行", "10d", "资金流入净额")}


def _em_flow(day: str, span: str) -> pd.Series | None:
    """Eastmoney's main-force net inflow (code -> yuan) over 5 or 10 days to ``day``."""
    from tradingagents.dataflows.vendors.akshare.sentiment import _dated

    n = span[:-1]
    try:
        df = _dated(f"em_fund_flow_{span}", day.replace("-", ""), not store.is_intraday(),
                    lambda: store.ak().stock_individual_fund_flow_rank(indicator=f"{n}日"), f"Eastmoney {n}-day fund flow")
    except Exception as e:  # noqa: BLE001 — Eastmoney rate-limits
        log.info("%s Eastmoney fund flow: %s", span, e)
        return None
    col = f"{n}日主力净流入-净额"
    if df is None or col not in df:
        return None
    s = pd.to_numeric(df[col], errors="coerce")
    s.index = df["代码"].astype(str).str.zfill(6)
    return market._unique(s)


def _ths_flow(day: str, span: str) -> pd.Series | None:
    """同花顺's net inflow (code -> yuan) over ``span`` to ``day``: its tables carry no history,
    so the latest session only. Shared with the analysts' copy (``sentiment/ths_fund_flow_*``)."""
    from tradingagents.dataflows.vendors.akshare.insiders import cn_number
    from tradingagents.dataflows.vendors.akshare.sentiment import _dated

    symbol, key, col = _THS_SPANS[span]
    try:
        df = _dated(f"ths_fund_flow_{key}", day.replace("-", ""), not store.is_intraday(),
                    lambda: store.ak().stock_fund_flow_individual(symbol=symbol), "同花顺 fund flow")
    except Exception as e:  # noqa: BLE001
        log.info("%s 同花顺 fund flow: %s", span, e)
        return None
    if df is None or col not in df or "股票代码" not in df:
        return None
    s = df[col].map(cn_number).astype(float)
    s.index = df["股票代码"].astype(str).str.zfill(6)
    return market._unique(s)


def _stock_flow(day: str, span: str) -> tuple[pd.Series | None, str | None]:
    """(code -> net inflow over ``span`` to ``day``, its source: eastmoney / ths). Eastmoney's
    main-force flow first; 同花顺's when Eastmoney fails. The latest closed day only, but for a
    day's own Eastmoney table already kept."""
    if span == "1d":
        flow, meta = market.main_flow(day)        # Eastmoney, or 同花顺 when Eastmoney fails
        return (flow, meta.get("source")) if flow is not None else (None, None)
    if pd.Timestamp(day).date() < store.last_closed_trade_date():
        return None, None
    em = _em_flow(day, span)
    if em is not None and len(em):
        return em, "eastmoney"
    ths = _ths_flow(day, span)
    return (ths, "ths") if ths is not None and len(ths) else (None, None)


def industry_flow(date: str | None = None, span: str = "1d", stock_flow=None) -> dict:
    """Net inflow summed by 申万一级 and 二级 industry over ``span``: Eastmoney's main-force flow,
    or 同花顺's (a different measure, said so in the reply) when Eastmoney fails."""
    if span not in FLOW_SPANS:
        raise ValueError(f"span must be one of {', '.join(FLOW_SPANS)}")
    day = market._days_on_record(date)[-1]
    got = (stock_flow or _stock_flow)(day, span)
    flow, source = got if isinstance(got, tuple) else (got, "eastmoney")
    if flow is None or not len(flow):
        why = ("只有最近一个交易日能取到" if day < market.last_closed_day()
               else "东方财富与同花顺资金流都暂不可用，稍后再试")
        return {"date": day, "span": span, "available": False, "note": f"{day} 的{span.replace('d', '日')}资金流不可得：{why}"}
    sectors = market.industries()
    df = pd.DataFrame({"flow": flow.groupby(level=0).last()})
    df = df.join(sectors[["sw1", "sw2"]], how="left")

    def by(col):
        g = df.dropna(subset=[col]).groupby(col)["flow"].sum().sort_values(ascending=False)
        return [{"name": k, "flow": _r(v, 0)} for k, v in g.items()]
    sw2 = df.dropna(subset=["sw2"]).assign(key=lambda x: x["sw1"].fillna("") + "-" + x["sw2"])
    g2 = sw2.groupby("key")["flow"].sum().sort_values(ascending=False)
    return {"date": day, "span": span, "available": True, "source": source,
            "label": "主力净流入" if source == "eastmoney" else "资金净流入（同花顺）",
            "source_note": None if source == "eastmoney" else THS_NOTE, "total": _r(df["flow"].sum(), 0),
            "sw1": by("sw1"), "sw2": [{"name": k.lstrip("-"), "flow": _r(v, 0)} for k, v in g2.items()]}


# ---------------------------------------------------------------------------
# 限售解禁: the shares that come off lock-up in the next 30 days (Eastmoney)
# ---------------------------------------------------------------------------
def releases(date: str | None = None, days: int = 30, summary=None, detail=None) -> dict:
    day = date or market.last_closed_day()
    end = (pd.Timestamp(day) + pd.Timedelta(days=days)).strftime("%Y-%m-%d")

    def build():
        s = (summary or (lambda a, b: store.ak().stock_restricted_release_summary_em(
            symbol="全部股票", start_date=a, end_date=b)))(day.replace("-", ""), end.replace("-", ""))
        d = (detail or (lambda a, b: store.ak().stock_restricted_release_detail_em(start_date=a, end_date=b)))(
            day.replace("-", ""), end.replace("-", ""))
        return (s, d), None
    (s, d), _ = _memo(f"releases_{day}", build)
    by_day = [{"date": pd.Timestamp(r["解禁时间"]).strftime("%Y-%m-%d"), "count": int(r["当日解禁股票家数"]),
               "value": _r(r["实际解禁市值"], 0)} for r in s.to_dict("records")] if s is not None and len(s) else []
    stocks = []
    if d is not None and len(d):
        d = d.assign(v=pd.to_numeric(d["实际解禁市值"], errors="coerce")).sort_values("v", ascending=False)
        stocks = [{"code": str(r["股票代码"]).zfill(6), "name": r["股票简称"],
                   "date": pd.Timestamp(r["解禁时间"]).strftime("%Y-%m-%d"), "kind": r["限售股类型"],
                   "value": _r(r["v"], 0), "float_share": _r(pd.to_numeric(r["占解禁前流通市值比例"], errors="coerce") * 100, 2)}
                  for r in d.head(30).to_dict("records")]
    total = sum(x["value"] or 0 for x in by_day)
    return {"date": day, "end": end, "total": total, "count": sum(x["count"] for x in by_day),
            "days": by_day, "stocks": stocks}


# ---------------------------------------------------------------------------
# 龙虎榜: the day's stocks on the exchanges' list, with the institutions' buying and selling
# ---------------------------------------------------------------------------
def _text(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


def _lhb_path(day: str):
    return store.root() / "web" / "lhb" / f"{day.replace('-', '')}.parquet"


def lhb(date: str | None = None, detail=None, inst=None) -> dict:
    day = market._days_on_record(date)[-1]
    path = _lhb_path(day)
    if path.exists():
        df = pd.read_parquet(path)
    else:
        key = day.replace("-", "")
        try:
            d = (detail or (lambda k: store.ak().stock_lhb_detail_em(start_date=k, end_date=k)))(key)
        except Exception as e:  # noqa: BLE001 — not published yet, or Eastmoney down
            return {"date": day, "available": False, "note": f"{day} 的龙虎榜不可得：{type(e).__name__}", "stocks": []}
        if d is None or not len(d):
            return {"date": day, "available": False, "note": f"{day} 的龙虎榜尚未公布（收盘后约 18:00 公布）", "stocks": []}
        try:
            j = (inst or (lambda k: store.ak().stock_lhb_jgmmtj_em(start_date=k, end_date=k)))(key)
        except Exception:  # noqa: BLE001 — the list without the institutions
            j = None
        d = d.assign(code=d["代码"].astype(str).str.zfill(6))
        d = d[~d["code"].str.startswith(("11", "12"))]          # convertible bonds are on the list too
        if not len(d):
            return {"date": day, "available": False, "note": f"{day} 的龙虎榜没有股票", "stocks": []}
        reasons = d.groupby("code")["上榜原因"].apply(lambda x: "；".join(dict.fromkeys(x.fillna("").astype(str))))
        df = d.drop_duplicates("code").set_index("code")
        df = pd.DataFrame({
            "name": df["名称"], "close": pd.to_numeric(df["收盘价"], errors="coerce"),
            "pct": pd.to_numeric(df["涨跌幅"], errors="coerce"), "net": pd.to_numeric(df["龙虎榜净买额"], errors="coerce"),
            "buy": pd.to_numeric(df["龙虎榜买入额"], errors="coerce"), "sell": pd.to_numeric(df["龙虎榜卖出额"], errors="coerce"),
            "net_share": pd.to_numeric(df["净买额占总成交比"], errors="coerce"),
            "turnover": pd.to_numeric(df["换手率"], errors="coerce"), "note": df["解读"].fillna("").astype(str),
            "reason": reasons.reindex(df.index),
        })
        if j is not None and len(j):
            j = j.assign(code=j["代码"].astype(str).str.zfill(6)).drop_duplicates("code").set_index("code")
            df["inst_buyers"] = pd.to_numeric(j["买方机构数"], errors="coerce").reindex(df.index)
            df["inst_sellers"] = pd.to_numeric(j["卖方机构数"], errors="coerce").reindex(df.index)
            df["inst_net"] = pd.to_numeric(j["机构买入净额"], errors="coerce").reindex(df.index)
        else:
            df["inst_buyers"] = df["inst_sellers"] = df["inst_net"] = float("nan")
        df = df.reset_index()
        if day < market.last_closed_day() or not store.is_intraday():
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(path)
    # The day's amount traded and volume (lots), from the market snapshot as in the 行情 table.
    try:
        _, xs = market.cross_section(day)
        xs = xs.assign(code=xs["code"].astype(str).str.zfill(6)).drop_duplicates("code").set_index("code")
        amount = pd.to_numeric(xs["amount"], errors="coerce")
        volume = pd.to_numeric(xs["volume"], errors="coerce")
    except Exception:  # noqa: BLE001 — the list without them
        amount = volume = pd.Series(dtype=float)
    stocks = [{"code": r["code"], "name": r["name"], "close": _r(r["close"]), "pct": _r(r["pct"]),
               "amount": _r(amount.get(r["code"]), 0), "volume": _r(volume.get(r["code"]), 0),
               "net": _r(r["net"], 0), "buy": _r(r["buy"], 0), "sell": _r(r["sell"], 0), "net_share": _r(r["net_share"]),
               "turnover": _r(r["turnover"]), "note": _text(r["note"]), "reason": _text(r["reason"]),
               "inst_buyers": None if pd.isna(r["inst_buyers"]) else int(r["inst_buyers"]),
               "inst_sellers": None if pd.isna(r["inst_sellers"]) else int(r["inst_sellers"]),
               "inst_net": _r(r["inst_net"], 0)} for r in df.to_dict("records")]
    stocks.sort(key=lambda x: -(x["net"] or 0))
    inst = [x["inst_net"] for x in stocks if x["inst_net"] is not None]
    return {"date": day, "available": True, "count": len(stocks), "net": _r(sum(x["net"] or 0 for x in stocks), 0),
            "inst_net": _r(sum(inst), 0) if inst else None,
            "inst_count": sum(1 for x in stocks if (x["inst_buyers"] or 0) + (x["inst_sellers"] or 0) > 0), "stocks": stocks}


def _seat_kind(name: str) -> str:
    if "机构专用" in name:
        return "机构"
    if "股通专用" in name:          # 沪股通专用 / 深股通专用: northbound money through Stock Connect
        return "北向"
    return "营业部"


def lhb_seats(code: str, date: str | None = None, fetch=None) -> dict:
    """The top five buying and top five selling seats of ``code`` on its 龙虎榜 day, by listing
    reason (a stock listed for two reasons has two sets). Kept with the analysts' copy, under
    ``sentiment/lhb_seats``, once the day is closed."""
    from tradingagents.dataflows.vendors.akshare.sentiment import _closed, _dated

    code = str(code).zfill(6)
    day = market._days_on_record(date)[-1]
    key = day.replace("-", "")
    get = fetch or (lambda flag: _dated("lhb_seats", f"{code}_{key}_{flag}", _closed(pd.Timestamp(day)),
                                        lambda: store.ak().stock_lhb_stock_detail_em(symbol=code, date=key, flag=flag),
                                        "Eastmoney 龙虎榜 seats"))
    sides: dict[str, pd.DataFrame] = {}
    for flag in ("买入", "卖出"):
        try:
            sides[flag] = get(flag)
        except Exception as e:  # noqa: BLE001 — not published yet, or Eastmoney down
            return {"code": code, "date": day, "available": False, "note": f"席位明细不可得：{type(e).__name__}", "groups": []}
    if all(t is None or not len(t) for t in sides.values()):
        return {"code": code, "date": day, "available": False, "note": f"{day} 没有该股的龙虎榜席位", "groups": []}

    def seat(r) -> dict:
        name = str(r["交易营业部名称"])
        num = lambda c: pd.to_numeric(r.get(c), errors="coerce")  # noqa: E731
        buy, sell = num("买入金额"), num("卖出金额")
        return {"seat": name, "kind": _seat_kind(name), "buy": _r(buy, 0), "sell": _r(sell, 0),
                "net": _r((0 if pd.isna(buy) else buy) - (0 if pd.isna(sell) else sell), 0),
                "buy_share": _r(num("买入金额-占总成交比例") * 100), "sell_share": _r(num("卖出金额-占总成交比例") * 100)}
    reasons = list(dict.fromkeys(
        str(x) for t in sides.values() if t is not None and len(t) and "类型" in t for x in t["类型"].dropna()))
    groups = []
    for reason in reasons or [""]:
        g = {"reason": reason}
        for flag, out in (("买入", "buy"), ("卖出", "sell")):
            t = sides.get(flag)
            if t is None or not len(t):
                g[out] = []
                continue
            if reason and "类型" in t:
                t = t[t["类型"].astype(str) == reason]
            g[out] = [seat(r) for r in t.to_dict("records")]
        # A seat in both lists: each row carries both sides, so its 净额 is the seat's own.
        # Not 机构专用: every institution goes by that one name, and they are different seats.
        bought_by = {x["seat"]: x for x in g["buy"] if x["kind"] != "机构"}
        sold_by = {x["seat"]: x for x in g["sell"] if x["kind"] != "机构"}
        for x in g["buy"]:
            other = sold_by.get(x["seat"])
            if other and x["sell"] is None:
                x.update(sell=other["sell"], sell_share=other["sell_share"], net=_r((x["buy"] or 0) - (other["sell"] or 0), 0))
        for x in g["sell"]:
            other = bought_by.get(x["seat"])
            if other and x["buy"] is None:
                x.update(buy=other["buy"], buy_share=other["buy_share"], net=_r((other["buy"] or 0) - (x["sell"] or 0), 0))
        # Every listed seat once (the top five each way, a seat in both lists counted once), as
        # Eastmoney's 龙虎榜买入额 / 卖出额: named seats by name, institutions by their amounts.
        listed = {(x["seat"], None, None) if x["kind"] != "机构" else (x["seat"], x["buy"], x["sell"]): x
                  for x in g["buy"] + g["sell"]}
        bought = sum(x["buy"] or 0 for x in listed.values())
        sold = sum(x["sell"] or 0 for x in listed.values())
        # The institutions' net: each institution row once (one in both lists is the same seat).
        inst = {(x["buy"], x["sell"]): x for x in g["buy"] + g["sell"] if x["kind"] == "机构"}
        g.update({"top_buy": _r(bought, 0), "top_sell": _r(sold, 0), "top_net": _r(bought - sold, 0),
                  "inst_net": _r(sum(x["net"] or 0 for x in inst.values()), 0) if inst else None})
        groups.append(g)
    return {"code": code, "date": day, "available": True, "groups": groups}


# ---------------------------------------------------------------------------
# 概念板块热度: 同花顺's concept boards, their change and money flow (latest day only)
# ---------------------------------------------------------------------------
CONCEPT_SPANS = {"1d": ("即时", "now"), "5d": ("5日排行", "5d"), "10d": ("10日排行", "10d")}


def _pct_text(v) -> float | None:
    """同花顺's "1.77%" (or a number) as 1.77."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(str(v).replace("%", "").strip())
    except ValueError:
        return None


def concepts(date: str | None = None, span: str = "1d", fetch=None) -> dict:
    """同花顺's concept boards over ``span`` (1d, 5d, 10d): change, money in and out (同花顺's
    measure: every trade by who started it) and the leading stock; its tables carry no history,
    so the latest closed day only."""
    from tradingagents.dataflows.vendors.akshare.sentiment import _dated

    if span not in CONCEPT_SPANS:
        raise ValueError(f"span must be one of {', '.join(CONCEPT_SPANS)}")
    day = market._days_on_record(date)[-1]
    if day < market.last_closed_day():
        return {"date": day, "span": span, "available": False, "note": f"{day} 的概念板块数据不可得：同花顺只提供最近一个交易日"}
    symbol, key = CONCEPT_SPANS[span]
    try:
        df = (fetch or (lambda: _dated(f"ths_concept_flow_{key}", day.replace("-", ""), not store.is_intraday(),
                                       lambda: store.ak().stock_fund_flow_concept(symbol=symbol), "同花顺 concept flow")))()
    except Exception as e:  # noqa: BLE001
        return {"date": day, "span": span, "available": False, "note": f"同花顺概念板块暂不可用：{type(e).__name__}"}
    if df is None or not len(df):
        return {"date": day, "span": span, "available": False, "note": "同花顺概念板块暂无数据"}
    pct_col = "行业-涨跌幅" if "行业-涨跌幅" in df else "阶段涨跌幅"
    num = lambda c: pd.to_numeric(df[c], errors="coerce") if c in df else pd.Series(float("nan"), index=df.index)  # noqa: E731
    rows = [{"name": str(r["行业"]), "pct": _pct_text(r.get(pct_col)), "count": None if pd.isna(c) else int(c),
             "inflow": _r(i * 1e8, 0), "outflow": _r(o * 1e8, 0), "net": _r(n * 1e8, 0),
             "leader": None if not isinstance(r.get("领涨股"), str) else r["领涨股"], "leader_pct": _pct_text(r.get("领涨股-涨跌幅"))}
            for r, c, i, o, n in zip(df.to_dict("records"), num("公司家数"), num("流入资金"), num("流出资金"), num("净额"), strict=False)]
    rows.sort(key=lambda x: -(x["pct"] if x["pct"] is not None else -1e9))
    ups = [x for x in rows if (x["pct"] or 0) > 0]
    return {"date": day, "span": span, "available": True, "count": len(rows), "up": len(ups),
            "net": _r(sum(x["net"] or 0 for x in rows), 0), "concepts": rows}


# ---------------------------------------------------------------------------
# 业绩预告: the latest report periods' forecasts (Eastmoney), by type and industry
# ---------------------------------------------------------------------------
GOOD = ("预增", "略增", "扭亏", "续盈", "减亏")
BAD = ("预减", "略减", "首亏", "续亏")
TYPE_ORDER = (*GOOD, *BAD, "不确定")


def _periods(day: str) -> list[pd.Timestamp]:
    """The four report periods a forecast on ``day`` can be for: the latest quarter end's year
    end ahead, then back."""
    d = pd.Timestamp(day)
    ends = [pd.Timestamp(year=y, month=m, day=31 if m in (3, 12) else 30) for y in (d.year - 1, d.year) for m in (3, 6, 9, 12)]
    return sorted([e for e in ends if e <= d + pd.offsets.YearEnd(0)], reverse=True)[:4]


def forecasts(date: str | None = None, period: str | None = None, table=None) -> dict:
    """The forecasts of a report period announced on or before ``date``: one per stock (the
    net profit attributable to shareholders), how many of each type, the share that are good
    news, by 申万一级 industry, and the biggest changes. Without ``period``: the latest period
    with at least 100 forecasts (or the one with the most)."""
    from tradingagents.dataflows.vendors.akshare.events import _period_table

    day = market._days_on_record(date)[-1]
    get = table or (lambda p: _period_table("yjyg", "stock_yjyg_em", p))
    # Every recent period, so the reply always lists them all (the page's period buttons), and the
    # one asked for even when it is older.
    candidates = _periods(day)
    if period and pd.Timestamp(period) not in candidates:
        candidates.append(pd.Timestamp(period))
    tables = {}
    for p in candidates:
        try:
            t = get(p)
        except Exception as e:  # noqa: BLE001
            log.info("forecasts %s: %s", p.date(), e)
            continue
        if t is None or not len(t):
            continue
        t = t[t["预测指标"].astype(str).str.contains("净利润") & ~t["预测指标"].astype(str).str.contains("扣除")]
        t = t[pd.to_datetime(t["公告日期"], errors="coerce") <= pd.Timestamp(day)]
        tables[p] = t.drop_duplicates("股票代码", keep="first")
    counts = {f"{p:%Y-%m-%d}": len(t) for p, t in tables.items()}
    if not tables:
        return {"date": day, "available": False, "note": "暂无业绩预告数据", "periods": counts}
    pick = pd.Timestamp(period) if period else next((p for p in tables if len(tables[p]) >= 100), max(tables, key=lambda p: len(tables[p])))
    t = tables.get(pick)
    if t is None or not len(t):
        return {"date": day, "available": False, "note": f"{pick:%Y-%m-%d} 没有业绩预告", "periods": counts}
    t = t.assign(code=t["股票代码"].astype(str).str.zfill(6), kind=t["预告类型"].astype(str),
                 chg=pd.to_numeric(t["业绩变动幅度"], errors="coerce"))
    sectors = market.industries()
    t = t.join(sectors[["sw1"]], on="code")
    types = [{"type": k, "count": int((t["kind"] == k).sum()), "good": k in GOOD} for k in TYPE_ORDER if (t["kind"] == k).any()]
    good = int(t["kind"].isin(GOOD).sum())
    by_ind = []
    for name, g in t.dropna(subset=["sw1"]).groupby("sw1"):
        n_good = int(g["kind"].isin(GOOD).sum())
        by_ind.append({"name": name, "count": int(len(g)), "good": n_good, "good_share": _r(n_good / len(g) * 100, 1),
                       "median_chg": _r(g["chg"].median())})
    by_ind.sort(key=lambda x: (-x["count"], x["name"]))

    def row(r) -> dict:
        return {"code": r["code"], "name": r["股票简称"], "type": r["kind"], "chg": _r(r["chg"]),
                "date": str(r["公告日期"])[:10], "industry": r["sw1"] if isinstance(r["sw1"], str) else None,
                "what": _text(r["业绩变动"])}
    best = t.dropna(subset=["chg"]).sort_values("chg", ascending=False).head(15)
    latest = t.sort_values("公告日期", ascending=False).head(15)
    return {"date": day, "available": True, "period": f"{pick:%Y-%m-%d}", "periods": counts, "count": int(len(t)),
            "good": good, "good_share": _r(good / len(t) * 100, 1), "types": types, "industries": by_ind,
            "best": [row(r) for r in best.to_dict("records")], "latest": [row(r) for r in latest.to_dict("records")]}
