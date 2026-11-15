"""A-share corporate events for ``get_corporate_events``: lock-up expiries and early results.

  限售解禁   restricted shares becoming tradable: the last LOCKUP_DAYS and the next
             LOCKUP_DAYS around the run date (Eastmoney, with Sina's announcement dates)
  业绩预告   earnings preannouncements (ranges for net profit, revenue ...) for the
             report periods around the run date (Eastmoney)
  业绩快报   preliminary results published ahead of the full report (Eastmoney)

Point in time: a preannouncement or preliminary result is served only once
announced (公告日期) by the run date. An expiry already past is served as it
happened; an upcoming one only when Sina dates its announcement by the run date,
since a past run could not have known a schedule announced later. Eastmoney's
returns after an expiry and the market value of an upcoming one (priced at today's
close) are never read.
"""
from __future__ import annotations

import pandas as pd

from tradingagents.dataflows.date_window import get_current_date
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.symbols import normalize_symbol
from tradingagents.dataflows.vendors.akshare import store
from tradingagents.dataflows.vendors.akshare.prices import require_code

LOCKUP_DAYS = 365         # past and upcoming window for expiries
PERIODS_BACK = 3          # report periods ended before the run date that are checked
PERIOD_SETTLED_DAYS = 200  # after this long past a period end, its announcements are final
REASON_CHARS = 200


def _num(v) -> float:
    v = pd.to_numeric(v, errors="coerce")
    return float("nan") if pd.isna(v) else float(v)


def _shares(v) -> str:
    v = _num(v)
    if pd.isna(v):
        return "—"
    return f"{v / 1e8:.2f}亿股" if abs(v) >= 1e8 else f"{v / 1e4:.2f}万股"


def _yuan(v) -> str:
    v = _num(v)
    if pd.isna(v):
        return "—"
    return f"{v / 1e8:.2f}亿元" if abs(v) >= 1e8 else f"{v / 1e4:.1f}万元"


def _pct(v, scale: float = 1.0) -> str:
    v = _num(v)
    return "—" if pd.isna(v) else f"{v * scale:.2f}%"


def _table(header: list[str], rows: list[list[str]]) -> str:
    return ("| " + " | ".join(header) + " |\n|" + "---|" * len(header) + "\n"
            + "".join("| " + " | ".join(r) + " |\n" for r in rows))


# ---------------------------------------------------------------------------
# 限售解禁
# ---------------------------------------------------------------------------
def _per_stock(kind: str, code: str, fn, what: str) -> pd.DataFrame:
    def get():
        df = store.call(fn, what)
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    return store.symbol_cache(kind, code, get)


def _lockups(code: str, as_of: pd.Timestamp) -> str:
    em = _per_stock("lockup_em", code, lambda: store.ak().stock_restricted_release_queue_em(symbol=code),
                    "Eastmoney 限售解禁")
    try:
        sina = _per_stock("lockup_sina", code, lambda: store.ak().stock_restricted_release_queue_sina(symbol=code),
                          "Sina 限售解禁")
    except VendorUnavailableError:
        sina = pd.DataFrame()
    if em.empty:
        return "No restricted-share expiry on record for this stock.\n"
    df = em.assign(_d=pd.to_datetime(em["解禁时间"], errors="coerce")).dropna(subset=["_d"])
    announced = {}
    if not sina.empty and {"解禁日期", "公告日期"} <= set(sina.columns):
        announced = dict(zip(pd.to_datetime(sina["解禁日期"], errors="coerce"),
                             pd.to_datetime(sina["公告日期"], errors="coerce"), strict=False))
    past = df[(df["_d"] <= as_of) & (df["_d"] > as_of - pd.Timedelta(days=LOCKUP_DAYS))].sort_values("_d")
    future = df[(df["_d"] > as_of) & (df["_d"] <= as_of + pd.Timedelta(days=LOCKUP_DAYS))].sort_values("_d")
    known = future[future["_d"].map(lambda d: pd.notna(announced.get(d)) and announced[d] <= as_of)]
    undated = len(future) - len(known)
    out = ""
    if len(known):
        rows = [[f"{r['_d']:%Y-%m-%d}", str(r["限售股类型"]), _shares(r["解禁数量"]), _pct(r["占总市值比例"], 100),
                 _pct(r["占流通市值比例"], 100), str(int(_num(r["解禁股东数"]))) if pd.notna(_num(r["解禁股东数"])) else "—",
                 f"{announced[r['_d']]:%Y-%m-%d}"] for _, r in known.iterrows()]
        out += f"Upcoming expiries (next {LOCKUP_DAYS} days, announced by {as_of:%Y-%m-%d}):\n" + _table(
            ["解禁日", "限售股类型", "解禁数量", "占总股本", "占流通股", "股东数", "公告日"], rows)
        out += ("- 占总股本 / 占流通股 are shares unlocking against the share capital; the market value "
                "is not given, as it would be priced at a later close.\n")
    else:
        out += f"No upcoming expiry in the next {LOCKUP_DAYS} days announced by {as_of:%Y-%m-%d}.\n"
    if undated:
        out += (f"- {undated} later-scheduled expir{'y is' if undated == 1 else 'ies are'} on record without an "
                f"announcement date on or before {as_of:%Y-%m-%d}, so not shown.\n")
    if len(past):
        rows = [[f"{r['_d']:%Y-%m-%d}", str(r["限售股类型"]), _shares(r["解禁数量"]), _shares(r["实际解禁数量"]),
                 _yuan(r["实际解禁数量市值"]), _pct(r["占流通市值比例"], 100)] for _, r in past.iterrows()]
        out += f"\nPast expiries (last {LOCKUP_DAYS} days):\n" + _table(
            ["解禁日", "限售股类型", "解禁数量", "实际解禁", "实际解禁市值", "占流通市值"], rows)
    else:
        out += f"No expiry in the last {LOCKUP_DAYS} days.\n"
    return out


# ---------------------------------------------------------------------------
# 业绩预告 / 业绩快报
# ---------------------------------------------------------------------------
def _periods(as_of: pd.Timestamp) -> list[pd.Timestamp]:
    """Report periods whose early results a run on ``as_of`` may see, newest first.

    The next period is included: an annual forecast often comes out with the Q3 report.
    """
    ends = pd.date_range(as_of - pd.DateOffset(months=3 * PERIODS_BACK + 3), as_of + pd.DateOffset(months=3),
                         freq="QE")
    return sorted(ends, reverse=True)


def _period_table(kind: str, fn_name: str, period: pd.Timestamp) -> pd.DataFrame:
    """The whole market's table for one report period.

    Cached for good once the period has settled, else for the trading day. An empty
    table (nothing announced) is cached for the day only, so a glitch is not kept.
    """
    key = f"{period:%Y%m%d}"
    settled = (pd.Timestamp(get_current_date()) - period).days > PERIOD_SETTLED_DAYS
    day = f"{store.last_closed_trade_date():%Y%m%d}"
    folder = store.root() / "events"
    for stamp in ("final", day):
        if (folder / f"{kind}_{key}__{stamp}.pkl").exists():
            return pd.read_pickle(folder / f"{kind}_{key}__{stamp}.pkl")
    try:
        df = store.call(lambda: getattr(store.ak(), fn_name)(date=key), f"Eastmoney {kind}")
    except VendorUnavailableError as e:
        # For a period with nothing announced yet, Eastmoney sends no data block and
        # AKShare fails on it (TypeError / KeyError) rather than returning an empty table.
        if not isinstance(e.__cause__, (TypeError, KeyError)):
            raise
        df = None
    df = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    stamp = "final" if settled and len(df) else day
    path = folder / f"{kind}_{key}__{stamp}.pkl"
    if not (stamp != "final" and store.is_intraday()):
        folder.mkdir(parents=True, exist_ok=True)
        df.to_pickle(path)
        for old in folder.glob(f"{kind}_{key}__*.pkl"):
            if old != path:
                old.unlink(missing_ok=True)
    return df


def _label(period: pd.Timestamp) -> str:
    return {3: "一季报", 6: "半年报", 9: "三季报", 12: "年报"}[period.month] + f" {period.year}"


def _for_stock(df: pd.DataFrame, code: str, as_of: pd.Timestamp) -> pd.DataFrame:
    if df.empty or "股票代码" not in df:
        return pd.DataFrame(columns=["_a"])
    hit = df[df["股票代码"].astype(str).str.zfill(6) == code].copy()
    hit["_a"] = pd.to_datetime(hit["公告日期"], errors="coerce")
    return hit[hit["_a"] <= as_of]


def _forecasts(code: str, as_of: pd.Timestamp) -> tuple[str, str, int]:
    """The 业绩预告 and 业绩快报 sections, and how many periods could not be read."""
    fc, qr, failed = [], [], 0
    for period in _periods(as_of):
        try:
            yg = _for_stock(_period_table("yjyg", "stock_yjyg_em", period), code, as_of)
            kb = _for_stock(_period_table("yjkb", "stock_yjkb_em", period), code, as_of)
        except VendorUnavailableError:
            failed += 1
            continue
        last_reason = None
        for _, r in yg.sort_values("_a", ascending=False).iterrows():
            reason = str(r.get("业绩变动原因") or "")
            reason = "" if reason in ("nan", "None") else reason[:REASON_CHARS] + ("…" if len(reason) > REASON_CHARS else "")
            # One announcement gives the same reason for every indicator: write it once.
            reason, last_reason = ("同上" if reason and reason == last_reason else reason), reason
            fc.append([_label(period), f"{r['_a']:%Y-%m-%d}", str(r["预告类型"]), str(r["预测指标"]),
                       str(r["业绩变动"]).replace("|", "/"), _pct(r["业绩变动幅度"]), _yuan(r["上年同期值"]),
                       reason.replace("|", "/").replace("\n", " ") or "—"])
        for _, r in kb.sort_values("_a", ascending=False).iterrows():
            qr.append([_label(period), f"{r['_a']:%Y-%m-%d}", _yuan(r["营业收入-营业收入"]),
                       _pct(r["营业收入-同比增长"]), _yuan(r["净利润-净利润"]), _pct(r["净利润-同比增长"]),
                       "—" if pd.isna(_num(r["每股收益"])) else f"{_num(r['每股收益']):.4f}",
                       _pct(r["净资产收益率"])])
    span = f"{_label(_periods(as_of)[-1])} to {_label(_periods(as_of)[0])}"
    note = (" A preannouncement is mandatory only in set cases (a loss, a swing of 50% or more, a turnaround),"
            " so its absence is normal and says nothing about results.")
    yg_text = (_table(["报告期", "公告日", "预告类型", "预测指标", "业绩变动", "变动幅度(中值)", "上年同期", "变动原因"], fc)
               if fc else f"No preannouncement published by {as_of:%Y-%m-%d} for {span}.{note}\n")
    kb_text = (_table(["报告期", "公告日", "营业收入", "营收同比", "归母净利润", "净利润同比", "每股收益", "ROE"], qr)
               if qr else f"No preliminary result published by {as_of:%Y-%m-%d} for {span}; most companies "
                          "go straight to the full report.\n")
    return yg_text, kb_text, failed


def get_corporate_events(ticker: str, as_of_date: str | None = None) -> str:
    """Lock-up expiries, earnings preannouncements and preliminary results for an A-share, as of ``as_of_date``."""
    code = require_code(ticker)
    as_of_text = as_of_date or get_current_date()
    as_of = pd.Timestamp(as_of_text)
    errors = []
    try:
        lock = _lockups(code, as_of)
    except VendorUnavailableError as e:
        errors.append(e)
        lock = f"<unavailable: {str(e)[:160]}>\n"
    yg, kb, failed = _forecasts(code, as_of)
    if failed:
        errors.append(failed)
        miss = f"\n<{failed} report period(s) could not be read from Eastmoney; this section may be incomplete>\n"
        yg, kb = yg + miss, kb + miss
    if len(errors) == 2 and failed == len(_periods(as_of)):
        raise VendorUnavailableError(f"AKShare corporate events unavailable for {normalize_symbol(ticker)}")
    return (f"# A-share corporate events for {normalize_symbol(ticker)}\n"
            f"# Point-in-time as of: {as_of_text} (only what was announced by then)\n\n"
            f"## 限售解禁 (restricted shares becoming tradable)\n{lock}\n"
            f"## 业绩预告 (earnings preannouncements)\n{yg}\n"
            f"## 业绩快报 (preliminary results)\n{kb}")
