"""宽基ETF加仓指数 for the analysts: the "national team"'s broad-based ETFs, to the analysis date.

The 19 broad-based ETFs' volume can be traded back and forth, but their shares only move when units
are created or redeemed, so their total is where the big money shows. This reads what the web app's
宽基ETF page computes (``web.server.etf_flow``: the shares from 上交所 and 深交所, kept on disk):

  份额变化   the 20's total daily change in shares (亿份): the raw series, noisy day to day
  加仓指数   total shares ÷ the total on the base day × 100 (each fund weighted by its part of
             the base total); 较前日 = the day's change ÷ the base total × 100
  5 / 20 日  the index's change over 5 / 20 trading days: the speed of adding or redeeming
  上轨 / 下轨 above 70 the bottom is near; below 30 it is time to cut positions
  规模       each fund's shares × its close that day (亿元): the funds are ranked by it, day by day

Imported lazily, so a checkout without the web app gives a plain "unavailable" note. Nothing after
the analysis date is read: the days asked for stop at it.
"""
from __future__ import annotations

import pandas as pd

ROWS = 10        # trading days in the table


def _unavailable(why: str) -> str:
    return f"宽基ETF加仓指数 is unavailable: {why}"


def _f(v, nd: int = 2, sign: bool = False) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{float(v):+.{nd}f}" if sign else f"{float(v):.{nd}f}"


def _by_size(etf_flow, wide: pd.DataFrame, day: str, base: str) -> list[str]:
    """The funds ranked by their size that day (shares × close), with shares and their changes."""
    try:
        size = etf_flow.sizes(day, wide)
    except Exception:  # noqa: BLE001 - the ranking is extra: without closes, by shares
        size = pd.Series(dtype=float)
    shares, prev = wide.loc[day], (wide.shift(1).loc[day])
    first = wide.loc[wide.index[wide.index <= base][-1]]
    if size.empty:
        order, head = shares.sort_values(ascending=False).index, f"按 {day} 份额排序（收盘价暂缺，规模未算）："
    else:
        order = list(size.index) + [c for c in shares.index if c not in size.index]
        head = f"按 {day} 规模排序（规模 = 当日份额 × 当日收盘价）："
    lines = ["", head, "| 名称 | 规模(亿元) | 份额(亿份) | 当日变化(亿份) | 较基期 |", "|---|---|---|---|---|"]
    for c in order:
        lines.append(f"| {etf_flow.NAMES[c]} | {_f(size.get(c))} | {_f(shares[c] / 1e8)} | "
                     f"{_f((shares[c] - prev[c]) / 1e8, sign=True)} | {_f(100 * (shares[c] / first[c] - 1), 1, sign=True)}% |")
    return lines


def get_broad_etf_flow(curr_date: str) -> str:
    """The 加仓指数 of the 20 broad-based ETFs on ``curr_date`` (or the last day published before
    it), where it sits against its bands, its rates, the day's biggest movers and the last
    ``ROWS`` trading days."""
    try:
        from web.server import etf_flow
    except Exception as e:  # noqa: BLE001 - no web app in this checkout
        return _unavailable(f"the ETF module could not be loaded ({type(e).__name__})")
    base = etf_flow.BASE
    if curr_date < base:
        return _unavailable(f"the index starts on its base day {base}, after {curr_date}")
    try:
        days = [d for d in etf_flow._trade_days() if d <= curr_date]
        with etf_flow._lock:
            wide, source, note = etf_flow.update(days)
        series = etf_flow.compute(wide, base)
    except Exception as e:  # noqa: BLE001 - the exchanges and nothing on disk
        return _unavailable(f"{type(e).__name__}: {str(e)[:160]}")

    s = series.set_index("date")
    day = s.index[-1]
    r = s.loc[day]
    if r["index"] >= etf_flow.UPPER:
        zone = f"在上轨 {etf_flow.UPPER} 之上：底部区间快出来了，相对接近底部"
    elif r["index"] <= etf_flow.LOWER:
        zone = f"在下轨 {etf_flow.LOWER} 之下：需要减仓了"
    else:
        zone = f"在下轨 {etf_flow.LOWER} 与上轨 {etf_flow.UPPER} 之间"
    since = s.loc[base:] if base in s.index else s
    lo, hi = since["index"].idxmin(), since["index"].idxmax()
    diff = (wide.diff() / 1e8).loc[day].dropna()
    top = diff.reindex(diff.abs().sort_values(ascending=False).index[:3])

    out = [f"# 宽基ETF加仓指数（国家队资金）截至 {day}", "",
           f"{len(etf_flow.FUNDS)} 只主要宽基 ETF（国家队重仓）的合计份额。份额只随申购、赎回变化（成交量可以对敲做出来），"
           "是大资金进出的痕迹。加仓指数 = 合计份额 ÷ 基期合计 × 100（每只按基期份额占比加权）；"
           "较前日 = 当日份额变化 ÷ 基期合计 × 100；5 / 20 日速率 = 指数 5 / 20 个交易日的变化（点）。", ""]
    if day < curr_date:
        out.append(f"（{curr_date} 的份额交易所尚未公布全部，以下截至 {day}。）")
    if note:
        out.append(f"（数据说明：{note}）")
    out += [f"{day}：加仓指数 {_f(r['index'])}（基期 {base} = 100），较前日 {_f(r['index_change'], sign=True)}；"
            f"合计 {_f(r['total'])} 亿份，较前日 {_f(r['change'], sign=True)} 亿份；"
            f"5 日速率 {_f(r['rate5'], sign=True)}，20 日速率 {_f(r['rate20'], sign=True)}。",
            f"位置：{zone}。基期以来最低 {_f(since.loc[lo, 'index'])}（{lo}），最高 {_f(since.loc[hi, 'index'])}（{hi}）。"]
    if len(top):
        out.append("当日份额变化最大：" + "，".join(f"{etf_flow.NAMES[c]} {_f(v, sign=True)} 亿份" for c, v in top.items()) + "。")
    out += _by_size(etf_flow, wide, day, base)
    out += ["", "| 日期 | 份额变化(亿份) | 加仓指数 | 较前日 | 5日速率 | 20日速率 |", "|---|---|---|---|---|---|"]
    for d, x in s.tail(ROWS).iterrows():
        out.append(f"| {d} | {_f(x['change'], sign=True)} | {_f(x['index'])} | {_f(x['index_change'], sign=True)} | "
                   f"{_f(x['rate5'], sign=True)} | {_f(x['rate20'], sign=True)} |")
    out += ["", "读法：指数持续上升、速率为正 = 大资金在申购宽基 ETF（加仓）；持续下降、速率为负 = 在赎回（减仓）；"
            "速率由负转正是由减转加。它描述整个 A 股市场的大资金动向，不是本股本身。"]
    return "\n".join(out)
