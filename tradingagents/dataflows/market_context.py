"""China A-share context for the analysts, from what the web app's 行情 page computes:

  get_industry_context(symbol, date)   the stock among its 申万 industries and peers: its
      一级 / 二级 / 三级, the industries' change over 5 and 20 days and rank, the stock's change
      and P/E against its peers, the industries' valuation percentile and crowding.
      For the market and fundamentals analysts (a tool).
  get_market_temperature(date, symbol)  the market's temperature: 情绪综合分, QVIX, the margin
      balance, the whole market's valuation and equity risk premium, and the day's limit-up
      themes (主线题材), with whether this stock was among them. For the sentiment analyst
      (fetched before it writes).

The web modules (``web.server.*``) are imported lazily, so a checkout without the web app or a
store without snapshots gives a plain "unavailable" note. Each section stands on its own: one
source failing leaves the others. Nothing dated after the analysis date is read.
"""
from __future__ import annotations

import logging

import pandas as pd

from tradingagents.dataflows.symbols import a_share_code

log = logging.getLogger(__name__)


def _f(v, nd: int = 2, suffix: str = "", sign: bool = False) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return (f"{float(v):+.{nd}f}" if sign else f"{float(v):.{nd}f}") + suffix


def _web():
    from web.server import breadth, extras, market, sectors
    return market, sectors, extras, breadth


def _day(market, date: str) -> str:
    """The latest day with whole-market data on or before ``date``."""
    return market._days_on_record(date)[-1]


def _section(out: list[str], title: str, build) -> None:
    try:
        lines = build()
    except Exception as e:  # noqa: BLE001 - one source failing leaves the others
        log.info("%s unavailable: %s", title, e)
        lines = [f"(unavailable: {type(e).__name__}: {str(e)[:120]})"]
    if lines:
        out += [f"## {title}", "", *lines, ""]


# ---------------------------------------------------------------------------
# Industry and peers
# ---------------------------------------------------------------------------
def _rank(values: pd.Series, mine: float | None) -> str:
    """'k/N' with 1 the highest; '—' without a value."""
    v = values.dropna()
    if mine is None or pd.isna(mine) or not len(v):
        return "—"
    return f"{int((v > mine).sum()) + 1}/{len(v)}"


def get_industry_context(symbol: str, curr_date: str) -> str:
    code = a_share_code(symbol)
    if not code:
        return "Industry context (申万 industries and peers) is available for China A-shares only."
    try:
        market, sectors, _, _ = _web()
        day = _day(market, curr_date)
        rows = pd.DataFrame(market.market_table(day)["rows"])
    except Exception as e:  # noqa: BLE001
        return f"Industry context is unavailable: {type(e).__name__}: {str(e)[:160]}"
    me = rows[rows["code"] == code]
    if me.empty:
        return f"Industry context is unavailable: {code} is not in the market table of {day}."
    me = me.iloc[0]
    sw1, sw2, sw3 = me.get("industry"), me.get("sub_industry"), me.get("industry3")
    out = [f"# {me['name']} ({code}) among its industries and peers, {day}", "",
           f"申万行业: 一级 {sw1 or '—'} · 二级 {sw2 or '—'} · 三级 {me.get('industry3') or '—'}", ""]
    if day < curr_date:
        out[-1:] = [f"(latest day with whole-market data: {day})", ""]

    def peers() -> list[str]:
        lines = ["| 范围 | 家数 | 当日涨跌 中位 | 本股当日排名 | 5日涨跌 中位 | 本股5日排名 | 市盈TTM 中位 | 总市值排名 |",
                 "|---|---|---|---|---|---|---|---|"]
        for label, col, name in (("三级", "industry3", sw3), ("二级", "sub_industry", sw2), ("一级", "industry", sw1)):
            if not name:
                continue
            g = rows[rows[col] == name]
            pe = g["pe_ttm"][g["pe_ttm"] > 0]
            lines.append(f"| {label} {name} | {len(g)} | {_f(g['pct_chg'].median(), 2, '%', True)} "
                         f"| {_rank(g['pct_chg'], me.get('pct_chg'))} | {_f(g['pct_5d'].median(), 2, '%', True)} "
                         f"| {_rank(g['pct_5d'], me.get('pct_5d'))} | {_f(pe.median(), 1)} "
                         f"| {_rank(g['total_mv'], me.get('total_mv'))} |")
        whole = rows["pct_chg"].median(), rows["pct_5d"].median()
        lines += ["", f"本股: 当日 {_f(me.get('pct_chg'), 2, '%', True)}, 5日 {_f(me.get('pct_5d'), 2, '%', True)}, "
                  f"市盈TTM {_f(me.get('pe_ttm'), 1) if (me.get('pe_ttm') or 0) > 0 else '亏损或无'}; "
                  f"全 A 中位: 当日 {_f(whole[0], 2, '%', True)}, 5日 {_f(whole[1], 2, '%', True)}"]
        if sw3:
            g = rows[rows["industry3"] == sw3].sort_values("pct_5d", ascending=False)
            top = "、".join(f"{r['name']} {_f(r['pct_5d'], 1, '%', True)}" for _, r in g.head(5).iterrows())
            lines.append(f"三级同行 5 日涨幅前列: {top}")
        return lines

    def industries() -> list[str]:
        lines = ["| 行业 | 5日涨跌 | 20日涨跌 | 20日排名 | 市盈率 | 市盈率历史分位 | 市净率分位 | 股息率 |",
                 "|---|---|---|---|---|---|---|---|"]
        for level, name in (("sw1", sw1), ("sw2", f"{sw1}-{sw2}" if sw1 and sw2 else None)):
            if not name:
                continue
            s = sectors.sectors(day, 20, level)
            table = pd.DataFrame(s["industries"])
            hit = table[table["name"] == name]
            if hit.empty:
                continue
            r = hit.iloc[0]
            lines.append(f"| {name} | {_f(r.get('cum5'), 2, '%', True)} | {_f(r.get('cum20'), 2, '%', True)} "
                         f"| {_rank(table['cum20'], r.get('cum20'))} | {_f(r.get('pe'), 1)} | {_f(r.get('pe_rank'), 0, '%')} "
                         f"| {_f(r.get('pb_rank'), 0, '%')} | {_f(r.get('dy'), 2, '%')} |")
        return lines if len(lines) > 2 else []

    def crowding() -> list[str]:
        c = sectors.crowding(day)
        hit = [x for x in c["industries"] if x["name"] == sw1]
        if not hit:
            return []
        x = hit[0]
        word = "拥挤" if x["crowd"] >= 80 else "冷清" if x["crowd"] <= 20 else "正常"
        return [f"{sw1}: 拥挤度 {_f(x['crowd'], 0)}（{word}；成交额占全 A {_f(x['share5'], 2, '%')}，近一年分位 "
                f"{_f(x['share_rank'], 0, '%')}；换手率分位 {_f(x['turnover_rank'], 0, '%')}），近 20 日涨跌 "
                f"{_f(x.get('cum20'), 1, '%', True)}。拥挤度 ≥ 80 时行业交易过热，回撤风险高；≤ 20 时少有人关注。"]

    _section(out, "本股与同行（当日 / 5日，排名 1 为最强）", peers)
    _section(out, "所属行业走势与估值（申万指数，估值分位为 2021 年以来）", industries)
    _section(out, "行业拥挤度（5 日成交额占比与换手率，相对近一年）", crowding)
    out.append("Read: a stock leading weak peers is idiosyncratic strength; one lagging strong peers is a laggard. "
               "Compare its P/E with the peers' median, not only with its own history.")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Market temperature
# ---------------------------------------------------------------------------
def get_market_temperature(curr_date: str, symbol: str | None = None) -> str:
    try:
        market, sectors, extras, breadth = _web()
        day = _day(market, curr_date)
    except Exception as e:  # noqa: BLE001
        return f"Market temperature is unavailable: {type(e).__name__}: {str(e)[:160]}"
    code = a_share_code(symbol) if symbol else None
    out = [f"# A-share market temperature to {day}", ""]

    def mood() -> list[str]:
        t = breadth._table(breadth._key())
        t = t[t.index <= day].tail(5)
        parts = breadth.MOOD_PARTS
        head = "| 日期 | 情绪综合分 | " + " | ".join(parts.values()) + " |"
        lines = [head, "|" + "---|" * (head.count("|") - 1)]
        for d, r in t.iterrows():
            lines.append(f"| {d} | {_f(r.get('mood'), 0)} | " + " | ".join(_f(r.get(f'm_{k}'), 0) for k in parts) + " |")
        lines.append("各项 0–100：≥ 70 情绪偏热，≤ 30 偏冷；综合分由涨跌比、涨停跌停比、封板率、涨停溢价、连板晋级率、空间板高度合成。")
        return lines

    def qvix() -> list[str]:
        q = extras.qvix(day, "1y")
        last = q["days"][-1] if q["days"] else None
        if not last:
            return []
        prev = q["days"][-6]["close"] if len(q["days"]) >= 6 else None
        return [f"QVIX（50ETF 期权隐含波动率，A 股的「恐慌指数」）{last['date']}: {_f(last['close'], 2)}，5 日前 {_f(prev, 2)}；"
                f"处于 {q['since']} 以来 {_f(q['rank'], 0, '%')} 分位（中位 {_f(q['median'], 2)}）。高位 = 恐慌、波动大；低位 = 平静。"]

    def margin() -> list[str]:
        m = extras.margin(day, "1y")
        d = m["days"]
        if not d:
            return []
        tot = pd.Series([x["total"] for x in d], index=[x["date"] for x in d], dtype=float)
        chg = lambda n: (tot.iloc[-1] - tot.iloc[-1 - n]) / 1e8 if len(tot) > n else None  # noqa: E731
        return [f"两融余额 {tot.index[-1]}: {tot.iloc[-1] / 1e12:.3f} 万亿；较 1 日前 {_f(chg(1), 0, '亿', True)}，"
                f"5 日 {_f(chg(5), 0, '亿', True)}，20 日 {_f(chg(20), 0, '亿', True)}"
                f"（近一年分位 {_f((tot < tot.iloc[-1]).mean() * 100, 0, '%')}）。杠杆资金持续流出时，反弹多难持续。"]

    def valuation() -> list[str]:
        v = sectors.valuation(day)
        d = pd.DataFrame(v["days"])
        if d.empty:
            return []
        r = d.iloc[-1]
        erp_rank = (d["erp"] < r["erp"]).mean() * 100
        pe_rank = (d["pe"] < r["pe"]).mean() * 100
        return [f"全 A 估值 {r['date']}: 市盈率 {_f(r['pe'], 2)}（{d['date'].iloc[0][:4]} 年以来 {pe_rank:.0f}% 分位），"
                f"市净率 {_f(r['pb'], 2)}，股息率 {_f(r['dy'], 2, '%')}；10 年国债 {_f(r['y10'], 3, '%')}，"
                f"股债性价比 ERP（1/PE − 国债收益率）{_f(r['erp'], 2, '%')}（{erp_rank:.0f}% 分位：越高股票相对越便宜）。"]

    def themes() -> list[str]:
        t = extras.themes(day, 5, top=10)
        if not t["have"]:
            return ["（涨停原因数据暂缺）"]
        lines = [f"近 5 个交易日（{t['dates'][0]} 至 {t['date']}）涨停原因中出现最多的题材（当日家数 / 5 日合计 / 出现天数）："]
        for x in t["themes"]:
            mine = " ← 本股当日涨停属此题材" if code and any(s["code"] == code for s in x["stocks"]) else ""
            lines.append(f"- {x['name']}: {x['today']} / {x['total']} / {x['days_on']} 天{mine}")
        if code:
            from web.server import limit_detail
            hits = []
            for d in t["dates"]:
                det = limit_detail.details(d)
                if det is not None and len(det) and "code" in det:
                    row = det[det["code"] == code]
                    if len(row):
                        hits.append(f"{d} 涨停（{row.iloc[0].get('reason') or '原因未披露'}）")
            lines.append(f"本股近 5 日: {'；'.join(hits) if hits else '未涨停'}。")
        return lines

    _section(out, "短线情绪（情绪综合分，近 5 日）", mood)
    _section(out, "波动率", qvix)
    _section(out, "杠杆资金", margin)
    _section(out, "全市场估值", valuation)
    _section(out, "主线题材", themes)
    out.append("These describe the whole market, not this stock: they set how much risk the market is taking, "
               "and whether the stock's theme is where the money is.")
    return "\n".join(out)
