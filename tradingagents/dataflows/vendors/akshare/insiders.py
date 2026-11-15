"""A-share insider trades: 董监高 (directors, supervisors, executives) and major shareholders.

The analysts' ``get_insider_transactions`` for an A-share, in two sections:

  董监高及相关人员  the exchange's own disclosure (SSE / SZSE / BSE), falling back
                    to 同花顺 (THS) 高管持股变动 when the exchange cannot be reached
  持股5%以上股东     同花顺 股东持股变动, dated by announcement (公告日期)

Point in time: a trade is served only once it was public on the run date. A
shareholder trade is public on its announcement date and an SSE filing on its
填报日期. SZSE, BSE and THS give only the trade date, and a 董监高 must report a
change within two trading days of it, so those trades are taken as public on the
second trading day after the trade.
"""
from __future__ import annotations

import re
from collections.abc import Callable

import pandas as pd

from tradingagents.dataflows.date_window import get_current_date
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.symbols import exchange_prefix, normalize_symbol
from tradingagents.dataflows.vendors.akshare import store
from tradingagents.dataflows.vendors.akshare.prices import require_code

LOOKBACK_DAYS = 365      # window of disclosures summarized and listed
TABLE_ROWS = 20          # most recent trades listed per section
DISCLOSURE_LAG = 2       # trading days a 董监高 has to report a change
PERIODS = (("3个月", 91), ("6个月", 182), ("12个月", 365))

COLUMNS = ["trade_date", "public_date", "dated_by", "name", "role", "shares", "price", "after", "method"]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
_CN_NUMBER = re.compile(r"(-?[\d,]*\.?\d+)\s*(万|亿)?")


def cn_number(value) -> float:
    """'增持4.16万' -> 41600, '减持40.43万' -> -404300, '5.82亿' -> 5.82e8, '未披露' -> NaN."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    m = _CN_NUMBER.search(s)
    if not m:
        return float("nan")
    v = float(m.group(1).replace(",", "")) * {"万": 1e4, "亿": 1e8}.get(m.group(2) or "", 1)
    return -abs(v) if "减" in s else v


def _num(s) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _dates(s) -> pd.Series:
    return pd.to_datetime(s.astype(str), errors="coerce", format="mixed").dt.normalize()


def _public_after_lag(trade_dates: pd.Series) -> pd.Series:
    """The second trading day after each trade date: the latest day its report is due."""
    cal = store.trade_calendar()

    def due(d):
        if pd.isna(d):
            return pd.NaT
        i = cal.searchsorted(d, side="right") + DISCLOSURE_LAG - 1
        return cal[i] if i < len(cal) else d + pd.offsets.BDay(DISCLOSURE_LAG)
    return trade_dates.map(due)


# ---------------------------------------------------------------------------
# Sources, each normalized to COLUMNS (shares signed, in shares; price in yuan)
# ---------------------------------------------------------------------------
def _fetch(kind: str, code: str, fn: Callable[[], pd.DataFrame], what: str) -> pd.DataFrame:
    def get():
        df = store.call(fn, what)
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    return store.symbol_cache(kind, code, get)


def _sse(code: str) -> pd.DataFrame:
    raw = _fetch("insider_sse", code, lambda: store.ak().stock_share_hold_change_sse(symbol=code),
                 "SSE 董监高 disclosure")
    if raw.empty:
        return pd.DataFrame(columns=COLUMNS)
    return pd.DataFrame({
        "trade_date": _dates(raw["变动日期"]), "public_date": _dates(raw["填报日期"]), "dated_by": "填报日期",
        "name": raw["姓名"].astype(str), "role": raw["职务"].astype(str),
        "shares": _num(raw["变动数"]), "price": _num(raw["本次变动平均价格"]),
        "after": _num(raw["变动后持股数"]), "method": raw["变动原因"].astype(str),
    })


def _szse(code: str) -> pd.DataFrame:
    raw = _fetch("insider_szse", code, lambda: store.ak().stock_share_hold_change_szse(symbol=code),
                 "SZSE 董监高 disclosure")
    if raw.empty:
        return pd.DataFrame(columns=COLUMNS)
    if "证券代码" in raw:      # the feed also serves the whole market
        raw = raw[raw["证券代码"].astype(str).str.zfill(6) == code]
    trade = _dates(raw["变动日期"])
    person = raw["股份变动人姓名"].astype(str)
    officer = raw["董监高姓名"].astype(str)
    relation = raw["变动人与董监高的关系"].astype(str)
    role = raw["职务"].astype(str).where(relation.isin(["本人", "nan", ""]),
                                       relation + " (" + officer + " " + raw["职务"].astype(str) + ")")
    return pd.DataFrame({
        "trade_date": trade, "public_date": _public_after_lag(trade), "dated_by": "变动日+2交易日",
        "name": person, "role": role,
        "shares": _num(raw["变动股份数量"]) * 1e4, "price": _num(raw["成交均价"]),
        "after": _num(raw["当日结存股数"]) * 1e4, "method": raw["变动原因"].astype(str),
    })


def _bse(code: str) -> pd.DataFrame:
    raw = _fetch("insider_bse", code, lambda: store.ak().stock_share_hold_change_bse(symbol=code),
                 "BSE 董监高 disclosure")
    if raw.empty:
        return pd.DataFrame(columns=COLUMNS)
    if "代码" in raw:
        raw = raw[raw["代码"].astype(str).str.zfill(6) == code]
    trade = _dates(raw["变动日期"])
    before, after = _num(raw["变动前持股数"]) * 1e4, _num(raw["变动后持股数"]) * 1e4
    # The feed's 变动股数 carries no sign; the holding before and after does.
    shares = (after - before).where(before.notna() & after.notna(), _num(raw["变动股数"]) * 1e4)
    return pd.DataFrame({
        "trade_date": trade, "public_date": _public_after_lag(trade), "dated_by": "变动日+2交易日",
        "name": raw["姓名"].astype(str), "role": raw["职务"].astype(str),
        "shares": shares, "price": _num(raw["变动均价"]), "after": after, "method": raw["变动原因"].astype(str),
    })


def _ths_executives(code: str) -> pd.DataFrame:
    raw = _fetch("insider_ths", code, lambda: store.ak().stock_management_change_ths(symbol=code),
                 "THS 高管持股变动")
    if raw.empty:
        return pd.DataFrame(columns=COLUMNS)
    trade = _dates(raw["变动日期"])
    return pd.DataFrame({
        "trade_date": trade, "public_date": _public_after_lag(trade), "dated_by": "变动日+2交易日",
        "name": raw["变动人"].astype(str), "role": raw["与公司高管关系"].astype(str),
        "shares": raw["变动数量"].map(cn_number), "price": _num(raw["交易均价"]),
        "after": raw["剩余股数"].map(cn_number), "method": raw["股份变动途径"].astype(str),
    })


_EXCHANGE_SOURCES = {"SH": (_sse, "上交所披露"), "SZ": (_szse, "深交所披露"), "BJ": (_bse, "北交所披露")}


def executive_trades(code: str) -> tuple[pd.DataFrame, str]:
    """董监高 trades and the source that served them: the exchange, else THS."""
    fetch, label = _EXCHANGE_SOURCES[exchange_prefix(code)]
    try:
        return fetch(code), label
    except Exception as exchange_error:  # noqa: BLE001 — exchange sites drop requests; THS covers them
        try:
            return _ths_executives(code), f"同花顺 (THS; {label} unreachable)"
        except Exception:  # noqa: BLE001
            raise exchange_error from None


def shareholder_trades(code: str) -> pd.DataFrame:
    """Major-shareholder (持股5%以上) trades, dated by announcement."""
    raw = _fetch("holder_ths", code, lambda: store.ak().stock_shareholder_change_ths(symbol=code),
                 "THS 股东持股变动")
    if raw.empty:
        return pd.DataFrame(columns=[*COLUMNS, "period"])
    period = raw["变动期间"].astype(str)
    trade = _dates(period.str.split("-").str[-1].str.replace(".", "-", regex=False))
    return pd.DataFrame({
        "trade_date": trade, "public_date": _dates(raw["公告日期"]), "dated_by": "公告日期",
        "name": raw["变动股东"].astype(str), "role": "股东",
        "shares": raw["变动数量"].map(cn_number), "price": _num(raw["交易均价"]),
        "after": raw["剩余股份总数"].map(cn_number), "method": raw["变动途径"].astype(str),
        "period": period,
    })


def mark_transferees(df: pd.DataFrame) -> pd.DataFrame:
    """Flag the receiving side of a transfer (询价转让, 大宗交易, 协议转让 ...).

    THS lists both sides of a transfer from a major shareholder: the seller's
    reduction and every buyer's receipt. A buyer is not an existing shareholder
    adding to a stake, so in an announcement (same 公告日期, 变动期间 and 方式)
    that has a seller, the increases are its transferees.
    """
    out = df.copy()
    out["transferee"] = False
    if out.empty:
        return out
    keys = ["public_date", "period" if "period" in out else "trade_date", "method"]
    sells = out[out["shares"] < 0].groupby(keys, dropna=False).size()
    has_seller = out.set_index(keys).index.isin(sells.index)
    out["transferee"] = has_seller & (out["shares"] > 0).to_numpy()
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _shares(v) -> str:
    if pd.isna(v):
        return "—"
    a = abs(v)
    s = f"{a / 1e8:.2f}亿" if a >= 1e8 else f"{a / 1e4:.2f}万" if a >= 1e4 else f"{a:,.0f}"
    return ("-" if v < 0 else "+") + s


def _yuan(v) -> str:
    if pd.isna(v):
        return "—"
    a = abs(v)
    s = f"{a / 1e8:.2f}亿元" if a >= 1e8 else f"{a / 1e4:.1f}万元"
    return ("-" if v < 0 else "+") + s


def _summary(df: pd.DataFrame, as_of: pd.Timestamp) -> str:
    lines = []
    for label, days in PERIODS:
        window = df[df["public_date"] > as_of - pd.Timedelta(days=days)]
        p = window[~window["transferee"]]
        received = window[window["transferee"]]
        buy, sell = p[p["shares"] > 0], p[p["shares"] < 0]
        value = (p["shares"] * p["price"]).sum(min_count=1)
        unpriced = int(p["price"].isna().sum())
        lines.append(
            f"- 近{label}: 增持 {len(buy)} 笔 {_shares(buy['shares'].sum()) if len(buy) else '0'}股, "
            f"减持 {len(sell)} 笔 {_shares(sell['shares'].sum()) if len(sell) else '0'}股, "
            f"净 {_shares(p['shares'].sum()) if len(p) else '0'}股 (≈{_yuan(value)}"
            + (f"; {unpriced} 笔未披露价格, 未计入金额" if unpriced else "") + ")"
            + (f"; 另有转让受让方 {len(received)} 家受让 {_shares(received['shares'].sum())}股, 不计入增持"
               if len(received) else ""))
    return "\n".join(lines) + "\n"


def _table(df: pd.DataFrame, with_period: bool) -> str:
    head = ["披露日", "变动日" if not with_period else "变动期间", "姓名", "职务/关系", "变动股数", "均价",
            "金额", "变动后持股", "方式"]
    rows = []
    keys = ["public_date", "period" if with_period else "trade_date", "method"]
    buyers = df[df["transferee"]].groupby(keys, dropna=False)
    shown_buyers = set()
    for _, r in df[~df["transferee"]].iterrows():
        when = r["period"] if with_period else f"{r['trade_date']:%Y-%m-%d}" if pd.notna(r["trade_date"]) else "—"
        public = f"{r['public_date']:%Y-%m-%d}" + ("" if r["dated_by"] in ("公告日期", "填报日期") else " (估)")
        rows.append([public, when, r["name"], r["role"], _shares(r["shares"]) + "股",
                     "—" if pd.isna(r["price"]) else f"{r['price']:.2f}", _yuan(r["shares"] * r["price"]),
                     _shares(r["after"]).lstrip("+") + "股" if pd.notna(r["after"]) else "—", r["method"]])
        key = tuple(r[k] for k in keys)
        if r["shares"] < 0 and key in buyers.groups and key not in shown_buyers:
            shown_buyers.add(key)
            g = buyers.get_group(key).sort_values("shares", ascending=False)
            names = "、".join(g["name"].head(3)) + (" 等" if len(g) > 3 else "")
            rows.append(["↳", "", f"受让方 {len(g)} 家 ({names})", "受让方", _shares(g["shares"].sum()) + "股",
                         "", _yuan((g["shares"] * g["price"]).sum(min_count=1)), "", r["method"]])
    out = "| " + " | ".join(head) + " |\n|" + "---|" * len(head) + "\n"
    return out + "".join("| " + " | ".join(map(str, r)) + " |\n" for r in rows)


def _section(title: str, source: str, df: pd.DataFrame, as_of: pd.Timestamp, with_period: bool = False) -> str:
    out = f"## {title}\nSource: {source}\n\n"
    known = df.dropna(subset=["public_date"])
    known = known[known["public_date"] <= as_of].sort_values(["public_date", "trade_date"], ascending=False)
    start = as_of - pd.Timedelta(days=LOOKBACK_DAYS)
    recent = known[known["public_date"] > start]
    if recent.empty:
        last = (f" The most recent disclosed trade before that was on {known['public_date'].iloc[0]:%Y-%m-%d}."
                if len(known) else " No trade has been disclosed at all in this record.")
        return out + f"No trade disclosed from {start:%Y-%m-%d} to {as_of:%Y-%m-%d}.{last}\n\n"
    recent = mark_transferees(recent)
    own = recent[~recent["transferee"]]
    listed = own.head(TABLE_ROWS)
    shown = recent[~recent["transferee"] | recent["public_date"].isin(listed["public_date"])]
    out += _summary(recent, as_of) + "\n" + _table(shown, with_period)
    if len(own) > TABLE_ROWS:
        out += f"\n({len(own) - TABLE_ROWS} earlier trades in the window not listed.)\n"
    return out + "\n"


def get_insider_transactions(ticker: str, as_of_date: str | None = None) -> str:
    """董监高 and major-shareholder trades disclosed by ``as_of_date`` (default: today)."""
    code = require_code(ticker)
    canonical = normalize_symbol(ticker)
    as_of_text = as_of_date or get_current_date()
    as_of = pd.Timestamp(as_of_text)
    parts, errors = [], []
    try:
        execs, source = executive_trades(code)
        parts.append(_section("董监高及相关人员增减持 (directors, supervisors, executives and their relatives)",
                              source, execs, as_of))
    except Exception as e:  # noqa: BLE001
        errors.append(e)
        parts.append(f"## 董监高及相关人员增减持\n<unavailable: {type(e).__name__}: {str(e)[:160]}>\n\n")
    try:
        parts.append(_section("持股5%以上股东增减持 (major shareholders)", "同花顺 (THS) 股东持股变动, by 公告日期",
                              shareholder_trades(code), as_of, with_period=True))
    except Exception as e:  # noqa: BLE001
        errors.append(e)
        parts.append(f"## 持股5%以上股东增减持\n<unavailable: {type(e).__name__}: {str(e)[:160]}>\n\n")
    if len(errors) == 2:
        raise VendorUnavailableError(f"AKShare insider trades unavailable for {canonical}: {errors[0]}")
    return (f"# A-share insider and major-shareholder trades for {canonical}\n"
            f"# Point-in-time as of: {as_of_text} (only trades public by then)\n\n"
            + "".join(parts)
            + "Notes: 披露日 marked (估) is the latest day the report was due (trade date + 2 trading days), for a "
              "source that gives no filing date. 大宗交易 and 协议转让 move blocks to identified buyers; 竞价交易 / "
              "二级市场 sells into the open market. Planned reductions (减持计划) announced but not yet executed "
              "are not in this record.\n")
