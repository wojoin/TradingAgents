"""China A-share context for the analysts, from what the web app's 行情 page computes:

  get_industry_context(symbol, date)   the stock among its 申万 industries and peers: its
      一级 / 二级 / 三级, the industries' change over 5 and 20 days and rank, the stock's change
      and P/E against its peers, the industries' valuation percentile and crowding.
      For the market and fundamentals analysts (a tool).
  get_market_temperature(date, symbol)  the market's temperature: 情绪综合分, QVIX, the margin
      balance (with its trend) and the policy events that changed a rule it trades on, the whole
      market's valuation and equity risk premium, and the day's limit-up themes (主线题材), with
      whether this stock was among them. For the sentiment analyst (fetched before it writes).

The web modules (``web.server.*``) are imported lazily, so a checkout without the web app or a
store without snapshots gives a plain "unavailable" note. Each section stands on its own: one
source failing leaves the others. Nothing dated after the analysis date is read.
"""
from __future__ import annotations

import logging
from datetime import date

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
# Margin trend
# ---------------------------------------------------------------------------
def _slope(s: pd.Series) -> float | None:
    """Least-squares slope of ``s`` against its position, per step (in ``s``'s own unit)."""
    v = s.dropna().reset_index(drop=True)
    if len(v) < 3:
        return None
    x = pd.Series(range(len(v)), dtype=float)
    dx = x - x.mean()
    denom = float((dx ** 2).sum())
    return float((dx * (v - v.mean())).sum() / denom) if denom else None


def margin_turn(slow: float, fast: float) -> str:
    """What the last five days say against the last twenty (both 亿/日); the 行情 page uses it too."""
    eps = max(abs(slow) * 0.05, 0.5)   # a move smaller than 5% of the trend is the same trend
    if slow > eps and fast <= 0:
        return "由增转减（去杠杆）"
    if slow < -eps and fast >= 0:
        return "由减转增（杠杆回补）"
    if slow > eps:
        return "加杠杆加快" if fast > slow else "加杠杆放缓"
    if slow < -eps:
        return "去杠杆加快" if fast < slow else "去杠杆放缓"
    return "基本走平"


def margin_trend(tot: pd.Series) -> list[str]:
    """The slope of a daily margin-balance series and whether leverage is speeding up or turning.

    A single day's change is noise: the 20-day slope says which way the leveraged money is
    moving and how fast, and the 5-day slope against it says whether that is speeding up,
    slowing or reversing. A reversal matters most: it is where the 20-day net change and the
    recent days disagree.
    """
    s20, s5 = _slope(tot.tail(20)), _slope(tot.tail(5))
    if s20 is None:
        return []
    slow = s20 / 1e8
    if s5 is None:
        return [f"两融趋势: 20 日斜率 {_f(slow, 1, '亿/日', True)}。"]
    fast = s5 / 1e8
    return [f"两融趋势: 20 日斜率 {_f(slow, 1, '亿/日', True)}，近 5 日 {_f(fast, 1, '亿/日', True)}，"
            f"{margin_turn(slow, fast)}。斜率转正且加快 = 杠杆资金在进场；由正转负 = 去杠杆。"]


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
        tot = pd.Series([x["total"] for x in d], index=[x["date"] for x in d], dtype=float).dropna()
        if tot.empty:
            return []

        def chg(n: int) -> float | None:
            return (tot.iloc[-1] - tot.iloc[-1 - n]) / 1e8 if len(tot) > n else None

        c20 = chg(20)
        prev20 = float(tot.iloc[-21]) if len(tot) > 20 else None
        pct20 = (tot.iloc[-1] - prev20) / prev20 * 100 if prev20 else None
        mom = f"20 日环比 {_f(pct20, 2, '%', True)}，" if pct20 is not None else ""
        return [f"两融余额 {tot.index[-1]}: {tot.iloc[-1] / 1e12:.3f} 万亿；较 1 日前 {_f(chg(1), 0, '亿', True)}，"
                f"5 日 {_f(chg(5), 0, '亿', True)}，20 日 {_f(c20, 0, '亿', True)}"
                f"（{mom}近一年分位 {_f((tot < tot.iloc[-1]).mean() * 100, 0, '%')}）。"
                f"杠杆资金持续流出时，反弹多难持续。"] + margin_trend(tot)

    def policy() -> list[str]:
        from tradingagents.dataflows.policy_events import events_between
        # by the analysis date, not the last trading day: a measure announced at the weekend
        # is known to a run dated that weekend, though the quotes are still Friday's.
        evs = events_between(curr_date)
        if not evs:
            return []
        mine = ""
        if code:
            try:
                ind = market.industries()
                mine = str(ind.loc[code, "sw1"]) if code in ind.index else ""
            except Exception as e:  # noqa: BLE001 - the events still read without the stock's industry
                log.info("industry for %s unavailable: %s", code, e)
        lines = []
        for e in evs:
            if e.effective <= curr_date:
                state = "已生效"
            else:
                state = f"{(date.fromisoformat(e.effective) - date.fromisoformat(curr_date)).days} 天后生效"
            parts = [f"- {e.effective}（{e.announced} 公布，{state}）【{e.kind}】{e.title}"]
            if e.params:
                parts.append("，".join(f"{n} {a} → {b}" for n, a, b in e.params))
            if e.scope:
                parts.append(f"范围 {e.scope}")
            if e.impact:
                parts.append(e.impact)
            if e.sectors:
                parts.append(f"涉及行业 {'、'.join(e.sectors)}")
            lines.append("；".join(parts) + (" ← 本股所在行业" if mine and mine in e.sectors else ""))
        lines.append("政策事件只改变资金供给与风险偏好，不改变公司盈利；已公布未生效的，"
                     "看生效前后两融余额与成交额的实际反应，而不是只看公告本身。")
        return lines

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
    _section(out, "政策与事件（改变交易规则或资金供给的已公布措施）", policy)
    _section(out, "全市场估值", valuation)
    _section(out, "主线题材", themes)
    out.append("These describe the whole market, not this stock: they set how much risk the market is taking, "
               "and whether the stock's theme is where the money is.")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 超跌反转 signal (the backtested buy combination)
# ---------------------------------------------------------------------------
def rebound_data(code: str, end: str | None = None) -> dict:
    """The stock's 超跌反转 signals since listing (to ``end``), today's setup and the market
    condition, from the local store; for the K-line markers and the analyst."""
    from tradingagents.dataflows import rebound_signal as rs
    market, _, _, breadth = _web()
    hist = market.history(code, end)
    bars = pd.DataFrame(hist["bars"]).rename(columns={"time": "date"})
    if end:
        bars = bars[bars["date"] <= end]
    if len(bars) < 60:
        return {"signals": [], "now": None, "market": None, "rule": rs.RULE, "stats": rs.STATS,
                "note": "上市不足 60 个交易日"}
    try:
        t = breadth._table(breadth._key())
        mcl = t["mcl_osc"].dropna()
        mcl = mcl[mcl.index <= bars["date"].iloc[-1]]
    except Exception as e:  # noqa: BLE001 - the signals stand without the market condition
        log.info("market MCL unavailable: %s", e)
        mcl = pd.Series(dtype=float)
    sig = rs.signals(bars, mcl)

    def book(trades: pd.DataFrame) -> tuple[set, dict]:
        """One position at a time: a purple 反 (the market condition held) buys only when nothing
        is held; a 反 while holding, or a grey one, is shown but not bought. Buys and sells alternate."""
        taken, skip, free_from = set(), {}, ""
        for r in sig.itertuples():
            if r.market_ok is not True:
                skip[r.date] = "市场条件不满足，不买" if r.market_ok is False else "无市场数据（2024-09 前），不买"
                continue
            if free_from is None or r.date < free_from:
                skip[r.date] = "持仓中，不重复买入"
                continue
            taken.add(r.date)
            t = trades.loc[r.date] if r.date in trades.index else None
            exit_date = t["exit_date"] if t is not None else None
            free_from = exit_date if isinstance(exit_date, str) else None      # None: still held
        return taken, skip

    trades = rs.exits(bars, sig).set_index("date") if len(sig) else pd.DataFrame()
    taken, skip = book(trades)
    best_trades = (rs.exits(bars, sig, rs.BEST_TAKE_PROFIT, rs.BEST_STOP_LOSS, rs.BEST_MAX_DAYS).set_index("date")
                   if len(sig) else pd.DataFrame())
    best_taken, _ = book(best_trades)
    num = lambda v, nd=2: None if v is None or pd.isna(v) else round(float(v), nd)  # noqa: E731

    def trade(d, trades=trades, taken=taken):
        if d not in taken or d not in trades.index:
            return None
        t = trades.loc[d]
        txt = lambda v: v if isinstance(v, str) else None  # noqa: E731 - NaN (no date yet) as null
        return {"entry_date": txt(t["entry_date"]), "exit_date": txt(t["exit_date"]), "sell_date": txt(t.get("sell_date")),
                "exit": t["exit"], "ret": num(t["ret"]), "days": int(t["days"]) if pd.notna(t["days"]) else None,
                "peak_date": txt(t.get("peak_date")), "peak_ret": num(t.get("peak_ret")),
                "entry_price": num(t.get("entry_price")), "exit_price": num(t.get("exit_price")),
                "target_price": num(t.get("target_price")), "stop_price": num(t.get("stop_price"))}
    out = [{"date": r.date, "trigger": r.trigger, "oversold": r.oversold, "adx": num(r.adx, 1), "mdi": num(r.mdi, 1),
            "pdi": num(r.pdi, 1), "amt_ratio": num(r.amt_ratio), "close": num(r.close), "stop": num(r.stop),
            "market_ok": r.market_ok, "trade": trade(r.date), "skip": skip.get(r.date)} for r in sig.itertuples()]
    closing = {trades.loc[d, "sell_date"] for d in taken if d in trades.index
               and isinstance(trades.loc[d, "sell_date"], str) and trades.loc[d, "exit"] == "卖"}
    sells = rs.sell_signals(bars, mcl, closing)
    sell_out = [{"date": r.date, "reason": r.reason, "gain20": num(r.gain20, 1), "adx": num(r.adx, 1),
                 "close": num(r.close), "market_weak": r.market_weak, "closes": r.date in closing}
                for r in sells.itertuples()]
    now = rs.setup_now(bars)
    market_now = None
    if len(mcl) > 3:
        market_now = {"date": mcl.index[-1], "mcl": num(mcl.iloc[-1], 1), "mcl_3d_ago": num(mcl.iloc[-4], 1),
                      "ok": bool(mcl.iloc[-1] > mcl.iloc[-4])}
    best = [{"date": d, **trade(d, best_trades, best_taken)} for d in sorted(best_taken)
            if trade(d, best_trades, best_taken) is not None]
    return {"best": {"rule": rs.BEST_RULE, "stats": rs.BEST_STATS, "trades": best}, "signals": out, "now": {k: (num(v, 1) if isinstance(v, float) else v) for k, v in now.items()},
            "market": market_now, "market_since": mcl.index[0] if len(mcl) else None,
            "rule": rs.RULE, "stats": rs.STATS,
            "sells": sell_out, "sell_rule": rs.SELL_RULE, "sell_stats": rs.SELL_STATS}


def get_rebound_signal(symbol: str, curr_date: str) -> str:
    code = a_share_code(symbol)
    if not code:
        return "The 超跌反转 signal is computed for China A-shares only."
    try:
        d = rebound_data(code, curr_date)
    except Exception as e:  # noqa: BLE001
        return f"The 超跌反转 signal is unavailable: {type(e).__name__}: {str(e)[:160]}"
    out = [f"# 超跌反转信号（组合 A）：{code}，截至 {curr_date}", "", f"规则：{d['rule']}", "", f"历史统计：{d['stats']}", ""]
    n = d.get("now")
    if n:
        missing = [x for x, ok in (("强下降趋势（ADX>25 且 −DI>+DI）", n["downtrend"]), ("超卖", n["oversold"])) if not ok]
        out += [f"## 当前（{n['date']}）", "",
                f"ADX {n['adx']}，+DI {n['pdi']}，−DI {n['mdi']}；%B {n['pctb']}，WR10 {n['wr10']}，RSI6 {n['rsi6']}；DIF {n['dif']}。",
                "形态条件已具备，等待触发（MACD 零轴下方金叉或 KDJ 金叉）与放量确认。" if not missing
                else f"形态条件未具备：缺 {'、'.join(missing)}。", ""]
    m = d.get("market")
    if m:
        out += [f"市场条件（{m['date']}）：全市场 MCL {m['mcl']}，3 日前 {m['mcl_3d_ago']} → {'满足（走高）' if m['ok'] else '不满足（未走高）'}。", ""]
    recent = d["signals"][-5:]
    if recent:
        out += ["## 最近的买入信号（最多 5 次）与卖出", "",
                "| 信号日 | 触发 | 超卖 | ADX | 成交额/5日均 | 收盘 | 市场条件 | 买入（次日开盘） | 卖出 | 收益（复权、未扣成本） |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        for s in recent:
            mk = "—" if s["market_ok"] is None else ("满足" if s["market_ok"] else "不满足")
            t = s.get("trade") or {}
            ex = {"卖": f"{t.get('exit_date')} 开盘卖出（{t.get('sell_date')} 出现「卖」）",
                  "盈": f"{t.get('exit_date')} 止盈 +30%（{t.get('exit_price')}）",
                  "止": f"{t.get('exit_date')} 止损 −15%（{t.get('exit_price')}）",
                  "期": f"{t.get('exit_date')} 持满 20 日卖出",
                  "持有中": f"持有中（{t.get('days')} 日；止盈价 {t.get('target_price')}，止损价 {t.get('stop_price')}）",
                  "待买入": "—"}.get(t.get("exit"), s.get("skip") or "—")
            ret = "—" if t.get("ret") is None else f"{t['ret']:+.2f}%"
            out.append(f"| {s['date']} | {s['trigger']} | {s['oversold']} | {s['adx']} | {s['amt_ratio']} | {s['close']} "
                       f"| {mk} | {t.get('entry_date') or '次日'} | {ex} | {ret} |")
        out.append("")
    else:
        out += ["上市以来没有出现完整信号。", ""]
    b = d.get("best") or {}
    if b:
        out += ["## ★ 单笔最优规则（胜率与单笔收益最高，持有更久）", "", f"规则：{b['rule']}", "", f"历史统计：{b['stats']}", ""]
        bt = b.get("trades", [])[-3:]
        if bt:
            out += ["| 信号日 | 买入 | 卖出 | 收益 |", "|---|---|---|---|"]
            for t in bt:
                how = {"盈": "止盈 +25%", "止": "止损 −30%", "期": "持满 250 日", "卖": "卖出信号", "持有中": "持有中"}.get(t["exit"], t["exit"])
                ret = "—" if t.get("ret") is None else f"{t['ret']:+.2f}%"
                out.append(f"| {t['date']} | {t.get('entry_date')} | {t.get('exit_date') or '—'} {how} | {ret} |")
            out.append("")
    out += ["## 卖出 / 规避信号", "", f"规则：{d['sell_rule']}", "", f"历史统计：{d['sell_stats']}", ""]
    if n:
        hot = n.get("gain20") is not None and n["gain20"] > 30
        out.append(f"当前：近 20 日涨幅 {n['gain20']:+.1f}%{'（> 30%，处于卖出 / 规避区）' if hot else ''}；"
                   f"{'强上升趋势（ADX>25 且 +DI>−DI）' if n.get('uptrend') else '非强上升趋势'}。" if n.get("gain20") is not None
                   else "当前：上市不足 20 日。")
        out.append("")
    recent_sells = d.get("sells", [])[-5:]
    if recent_sells:
        out += ["| 日期 | 原因 | 收盘 | 市场条件 |", "|---|---|---|---|"]
        for x in recent_sells:
            mk = "—" if x["market_weak"] is None else ("走弱（信号更强）" if x["market_weak"] else "走强")
            out.append(f"| {x['date']} | {x['reason']} | {x['close']} | {mk} |")
        out.append("")
    out.append("Use: a statistical edge across many stocks, not a forecast for this one; a signal within the last "
               "few days supports a rebound case (by the rule: +30% target, −15% stop, 20 days at most, or the next 卖). A recent sell / avoid signal says the "
               "stock has tended to lag the market for about 20 days after such a run, not that it must fall.")
    return "\n".join(out)
