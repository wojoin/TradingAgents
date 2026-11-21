"""China A-share market breadth for the analysts: the whole market's day-by-day readings up to
the analysis date, the structure each day reads as, and the three-step breadth verdict.

It reads what the web app's 行情 page computes from the local AKShare store (every A-share's
daily snapshot): ``web.server.breadth`` (the breadth table), ``web.server.breadth_verdict``
(market structure and the verdict) and ``web.server.market`` (daily counts, the 上证指数).
Imported lazily, so a checkout without the web app, or a store without snapshots, gives a
plain "unavailable" note instead of an error. Nothing after the analysis date is shown.

The readings (as in the 「市场研判」 tables these follow):

  涨/跌/平          stocks up, down and unchanged
  涨家占比          rising stocks' share of those traded (%)
  涨额占比 / 涨量占比  rising stocks' share of the amount / volume traded (%)
  额价差 / 量价差    涨额占比 − 涨家占比 and 涨量占比 − 涨家占比 (pp): > 0, the money / volume
                    is with the risers more than their number (资金强于宽度)
  TRIN_额 / TRIN_量  (up ÷ down stocks) ÷ (up ÷ down amount / volume): < 1, the money goes
                    with the risers; > 1, with the fallers
  净新高60          (60-day new highs − new lows) ÷ stocks traded (%)
  MCL              McClellan oscillator on the raw up − down count (EMA19 − EMA39)
  涨停 / 跌停        limit-up and limit-down closes
  P20 / P60 / P250  share of stocks above their 20 / 60 / 250-day average (%)
  全A成交额          amount traded (亿), and ÷ the 5 days before's average (放量 > 1.1, 缩量 < 0.9)
"""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)
MAX_DAYS = 30


def _unavailable(why: str) -> str:
    return f"Market breadth is unavailable: {why}"


def _f(v, nd: int = 2, pct: bool = False, sign: bool = False) -> str:
    if v is None or pd.isna(v):
        return "—"
    s = f"{float(v):+.{nd}f}" if sign else f"{float(v):.{nd}f}"
    return s + ("%" if pct else "")


def _i(v) -> str:
    return "—" if v is None or pd.isna(v) else str(int(v))


def _volume_word(r: float | None) -> str:
    if r is None or pd.isna(r):
        return ""
    return "放量" if r > 1.1 else "缩量" if r < 0.9 else "平量"


def get_market_breadth(curr_date: str, look_back_days: int = 10) -> str:
    """The A-share market's breadth over the ``look_back_days`` trading days to ``curr_date``
    (at most MAX_DAYS), oldest first, then the day's structure and the breadth verdict."""
    try:
        from web.server import breadth, breadth_verdict, market
    except Exception as e:  # noqa: BLE001 - no web app in this checkout
        return _unavailable(f"the breadth module could not be loaded ({type(e).__name__})")
    n = max(1, min(int(look_back_days or 10), MAX_DAYS))
    try:
        days = market._days_on_record(curr_date)
        table = breadth._table(breadth._key())
        stats, _ = market._span_stats(list(table.index))
    except Exception as e:  # noqa: BLE001 - no snapshots on disk
        return _unavailable(f"{type(e).__name__}: {str(e)[:160]}")
    end = days[-1]
    d = breadth_verdict.frame(table, stats, pd.Series(dtype=float))
    d = d[d.index <= end]
    if d.empty:
        return _unavailable(f"no breadth readings on or before {curr_date}")
    t = table.reindex(d.index)
    st = stats.set_index("date").reindex(d.index)
    amount = pd.to_numeric(st["amount"], errors="coerce")
    ratio5 = amount / amount.shift(1).rolling(5, min_periods=3).mean()
    try:
        sh = market.index_closes("上证指数").set_index("date")["close"]
        sh = sh[sh.index <= end]
    except Exception as e:  # noqa: BLE001 - the index is a nice-to-have here
        log.info("上证指数 unavailable for breadth: %s", e)
        sh = pd.Series(dtype=float)
    sh_pct = sh.pct_change() * 100
    label = {k: lab for k, lab, *_ in breadth_verdict.STRUCTURES}
    show = d.tail(n)

    head = ("| 日期 | 上证 | 涨/跌/平 | 涨家占比 | 涨额占比 | 涨量占比 | 额价差 | 量价差 | TRIN_额 | TRIN_量 "
            "| 净新高60 | MCL | 涨停/跌停 | P20/P60/P250 | 全A成交额 | 结构 |")
    lines = [head, "|" + "---|" * (head.count("|") - 1)]
    for day, r in show.iterrows():
        x = t.loc[day]
        close = sh.get(day)
        index = "—" if close is None or pd.isna(close) else f"{close:.2f} ({_f(sh_pct.get(day), 2, True, True)})"
        amt = amount.get(day)
        amt_s = "—" if pd.isna(amt) else f"{amt / 1e8:,.0f}亿 ×{_f(ratio5.get(day), 2)} {_volume_word(ratio5.get(day))}"
        lines.append(
            f"| {day} | {index} | {_i(r.n_up)}/{_i(r.n_down)}/{_i(r.n_flat)} | {_f(r.up_pct, 2, True)} "
            f"| {_f(x.get('up_amt_pct'), 2, True)} | {_f(x.get('up_vol_pct'), 2, True)} "
            f"| {_f(x.get('amt_gap'), 2, sign=True)}pp | {_f(x.get('vol_gap'), 2, sign=True)}pp "
            f"| {_f(r.trin_amt, 3)} | {_f(r.trin_vol, 3)} | {_f(x.get('net60_pct'), 2, True, True)} "
            f"| {_f(x.get('mcl_raw'), 1, sign=True)} | {_i(r.limit_up)}/{_i(r.limit_down)} "
            f"| {_f(x.get('ma20'), 1)}/{_f(x.get('ma60'), 1)}/{_f(x.get('ma250'), 1)} | {amt_s} "
            f"| {label.get(r.structure, '—') if r.structure else '—'} |")

    last = show.iloc[-1]
    out = [f"# A-share market breadth to {end} (every A-share on record; analysis date {curr_date})", ""]
    if end < curr_date:
        out += [f"Latest day with whole-market data: {end} (no later day on record).", ""]
    out += ["## Day by day (oldest first)", "", *lines, ""]
    rows = {k: (lab, rule, meaning) for k, lab, rule, meaning, *_ in breadth_verdict.STRUCTURES}
    if last.structure and last.structure in rows:
        lab, rule, meaning = rows[last.structure]
        out += [f"## Market structure on {end}: {lab}", "", f"- Rule: {rule}", f"- Reading: {meaning}", ""]
    try:
        v = breadth_verdict.verdict(end)
        c = v["conclusion"]
        out += [f"## Breadth verdict on {v['date']} (trend → timing → confirmation)", "",
                f"- {c['headline']}", f"- {c['text']}",
                f"- Short term (5 days): {c['short_word']}; medium term (20 days): {c['mid_word']}",
                *[f"- {p}" for p in c.get("points", [])[:4]], ""]
    except Exception as e:  # noqa: BLE001 - the table above still stands
        log.info("breadth verdict unavailable: %s", e)
    out += ["## How to read it", "",
            "- TRIN < 1 (and 额价差 > 0): the money is with the rising stocks, stronger than their number; "
            "TRIN > 1: the money is with the falling stocks.",
            "- 涨家占比 ≥ 60% is a broad rise, ≤ 40% a broad fall; a few rising stocks taking most of the money "
            "(low 涨家占比, TRIN < 0.8) is 少数股抱团, and TRIN climbing back toward 1 from there is the cluster breaking up.",
            "- MCL > 0 and rising: breadth momentum up; below 0 and falling: down. 净新高60 < 0: more stocks at "
            "60-day lows than highs. P20/P60/P250: how much of the market is above its short / medium / long average.",
            "- 放量 / 缩量: the amount against the 5 days before. These describe the whole market, not this stock: "
            "use them for the market backdrop and the risk of the timing, not as the stock's own signal."]
    return "\n".join(out)
