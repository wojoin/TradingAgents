"""超跌反转 (oversold rebound): the one buy combination that held up in the A-share backtest.

Backtest (every A-share 2021-01 → 2026-11, daily, adjusted; buy at the next day's open, skipped
when it opens at the upper limit; one signal per stock per 10 trading days; excess = less the
average of every stock over the same days):

  setup     ADX(14,6) > 25 and −DI > +DI (a strong downtrend), and in the last 5 days oversold:
            %B(20,2) < 0, WR(10) > 80 or RSI(6) < 20
  trigger   a MACD(12,26,9) golden cross below zero, or a KDJ(9,3,3) golden cross with K < 50
  confirm   the amount above its 5 days before's average, and the close back over the lower band
  market    the whole market's McClellan oscillator above its level 3 days before

  exit      all at once, whichever first from the day after the entry: the high reaching +30% (盈), the
            low reaching −15% (止), 20 trading days (期), a sell / avoid signal (卖, next open)

  20-day excess +0.30% (+0.45% with the market condition, win rate 53%, positive in each of
  2021–2026). One position at a time, bought on a purple 反 only, held to the next 卖, after a 0.15%
  round-trip cost: 33k trades, +7.1% a trade on average, median +6.9%, 60% won, +1.8% excess (2023
  negative), about 129 trading days held, the worst 5% about −40%, 14% not yet sold (held 20 days instead: +2.2% a trade but +2.4% per 20 days held, the better use of
  time; stops only cut the return). Breakouts after a squeeze and pull-backs in an uptrend lagged.

Computed on adjusted prices (rebuilt from each day's change), so ex-dividend gaps are no signal.
Every indicator uses data to the day only: a signal on day t is known at t's close.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

COOLDOWN = 10
RULE = ("超跌反转（组合 A）：ADX>25 且 −DI>+DI 的强下降趋势中，近 5 日出现超卖（%B<0、WR10>80 或 RSI6<20）；"
        "当日 MACD 零轴下方金叉或 KDJ 金叉（K<50）；放量（成交额高于前 5 日均值）且收盘回到布林下轨之上；"
        "市场条件：全市场 MCL 高于 3 日前（紫色）。买入：没有持仓时的紫色「反」，次日开盘一次性买入；"
        "卖出（一次性卖光，先到先卖，买入次日起）：盈 = 最高价达到买入价 +30%；止 = 最低价跌到买入价 −15%；"
        "期 = 持满 20 个交易日收盘；卖 = 出现卖出信号，次日开盘。")
STATS = ("全 A 股 2021-01 至 2026-11 回测（一次只持一笔，扣 0.15% 成本）：止盈 30% / 止损 15% / 期限 20 日 时，"
         "每笔平均 +2.0%、中位 +0.5%、胜率 52%、每笔超额 +0.8%（2021–2026 每年为正），平均持有 17 日，每 20 日 +2.4%，"
         "最差 5% 约 −15%；约 65% 到期、17% 止损、9% 止盈、6% 卖出信号。对比：止损 5% 每 20 日 +3.0% 但胜率 38%、多数小亏；"
         "止盈收窄（5–15%）收益明显变差。这是大量股票的历史统计，不是对单只股票的预测。")


def _sma_cn(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(alpha=1 / n, adjust=False).mean()


def indicators(bars: pd.DataFrame) -> pd.DataFrame:
    """The readings the rule uses, on adjusted prices. ``bars``: date, open, high, low, close,
    amount, pct_chg (unadjusted prices with each day's change), oldest first."""
    b = bars.reset_index(drop=True)
    close = b["close"].astype(float)
    pct = pd.to_numeric(b["pct_chg"], errors="coerce")
    adj = (1 + pct.fillna(0) / 100).cumprod()
    # The first bar's change is against the issue price: scale so the last close is the real one.
    fac = adj / close
    fac = fac / fac.iloc[-1] if pd.notna(fac.iloc[-1]) and fac.iloc[-1] else fac
    C = close * fac
    op, H, L = b["open"] * fac, b["high"] * fac, b["low"] * fac
    out = pd.DataFrame({"date": b["date"].astype(str)})
    ma20 = C.rolling(20, min_periods=20).mean()
    sd = C.rolling(20, min_periods=20).std(ddof=0)
    out["lb"] = ma20 - 2 * sd
    out["pctb"] = (C - out["lb"]) / (4 * sd) * 100
    chg = C.diff()
    out["rsi6"] = _sma_cn(chg.clip(lower=0), 6) / _sma_cn(chg.abs(), 6) * 100
    hh, ll = H.rolling(10, min_periods=10).max(), L.rolling(10, min_periods=10).min()
    out["wr10"] = (hh - C) / (hh - ll) * 100
    hh9, ll9 = H.rolling(9, min_periods=9).max(), L.rolling(9, min_periods=9).min()
    k = _sma_cn(((C - ll9) / (hh9 - ll9) * 100).fillna(50), 3)
    d = _sma_cn(k, 3)
    out["k"] = k
    out["kdj_up"] = (k > d) & (k.shift(1) <= d.shift(1))
    dif = C.ewm(span=12, adjust=False).mean() - C.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    out["dif"] = dif
    out["macd_up"] = (dif > dea) & (dif.shift(1) <= dea.shift(1))
    pc = C.shift(1)
    tr = np.fmax(np.fmax(H - L, (H - pc).abs()), (pc - L).abs())
    hd, ld = H - H.shift(1), L.shift(1) - L
    s14 = lambda x: x.rolling(14, min_periods=14).sum()  # noqa: E731
    mtr = s14(tr)
    out["pdi"] = s14(hd.where((hd > 0) & (hd > ld), 0)) * 100 / mtr
    out["mdi"] = s14(ld.where((ld > 0) & (ld > hd), 0)) * 100 / mtr
    out["adx"] = ((out["mdi"] - out["pdi"]).abs() / (out["mdi"] + out["pdi"]) * 100).rolling(6, min_periods=6).mean()
    out["atr14"] = tr.rolling(14, min_periods=14).mean()
    amount = pd.to_numeric(b.get("amount"), errors="coerce")
    out["amt_ratio"] = amount / amount.shift(1).rolling(5, min_periods=5).mean()
    out["close_adj"], out["open_adj"], out["close"] = C, op, close
    return out


def signals(bars: pd.DataFrame, market_mcl: pd.Series | None = None) -> pd.DataFrame:
    """Each day the full rule fired (one per COOLDOWN days), with its readings and whether the
    market condition held (True / False, or None without the market's series for that day).
    ``market_mcl``: the whole market's McClellan oscillator by date (YYYY-MM-DD)."""
    x = indicators(bars)
    oversold = (x["pctb"] < 0) | (x["wr10"] > 80) | (x["rsi6"] < 20)
    setup = ((x["adx"] > 25) & (x["mdi"] > x["pdi"]) & oversold).astype(float).rolling(5, min_periods=1).max().astype(bool)
    trig_macd = x["macd_up"] & (x["dif"] < 0)
    trig_kdj = x["kdj_up"] & (x["k"] < 50)
    confirm = (x["amt_ratio"] > 1) & (x["close_adj"] > x["lb"])
    fired = (setup & (trig_macd | trig_kdj) & confirm).to_numpy()
    keep, last = [], -10**9
    for i in np.flatnonzero(fired):
        if i - last > COOLDOWN:
            keep.append(i)
            last = i
    rows = x.iloc[keep].copy()
    rows["trigger"] = np.where(trig_macd.iloc[keep], "MACD 零轴下方金叉", "KDJ 金叉")
    rows["oversold"] = [("、".join(n for n, c in (("%B<0", r.pctb < 0), ("WR10>80", r.wr10 > 80), ("RSI6<20", r.rsi6 < 20)) if c)
                         or "近 5 日内") for r in rows.itertuples()]
    if market_mcl is not None and len(market_mcl):
        m = market_mcl.sort_index()
        up = (m > m.shift(3)).where(m.shift(3).notna())
        flags = [None if d not in up.index or pd.isna(up[d]) else bool(up[d]) for d in rows["date"]]
    else:
        flags = [None] * len(rows)
    rows["market_ok"] = pd.Series(flags, index=rows.index, dtype=object)     # True / False / None, as Python values
    rows["stop"] = rows["close"] - 2 * rows["atr14"] * rows["close"] / rows["close_adj"]
    return rows.reset_index(drop=True)


def _sell_condition(x: pd.DataFrame) -> pd.Series:
    """The sell / avoid condition each day: the 20-day gain over 30%, or a MACD golden cross in a
    strong uptrend with ADX rising."""
    C = x["close_adj"]
    hot = (C / C.shift(20) - 1) * 100 > 30
    chase = x["macd_up"] & (x["adx"] > 25) & (x["pdi"] > x["mdi"]) & (x["adx"] > x["adx"].shift(3))
    return (hot | chase).fillna(False)


# 「★ 单笔最优」: the rule with the highest win rate and gain a trade (not per unit of time) among those
# tried: a wide stop and a long hold.
BEST_TAKE_PROFIT = 0.25
BEST_STOP_LOSS = 0.30
BEST_MAX_DAYS = 250
BEST_RULE = ("★ 单笔最优：同样在紫色「反」次日开盘一次性买入（一次只持一笔）；卖出（一次性卖光，先到先卖，买入次日起）："
             "最高价达到买入价 +25% 止盈；最低价跌到 −30% 止损；持满 250 个交易日收盘卖出；或出现「卖」信号次日开盘卖出。")
BEST_STATS = ("全 A 股 2021-01 至 2026-11 回测（一次只持一笔，扣 0.15% 成本）：胜率 62.6%、每笔平均 +4.6%、中位 +11.6%、"
              "每笔超额 +1.9%（2021–2026 每年为正）；平均持有约 69 个交易日，最差的交易亏损约 30%；约 40% 止盈、22% 止损、"
              "25% 卖出信号、4% 到期。对比短线规则（30% / 15% / 20 日）：胜率 52%、每笔 +2.0%、平均持有 17 日。"
              "这是大量股票的历史统计，不是对单只股票的预测。")

TAKE_PROFIT = 0.30          # 盈: sold when the day's high reaches entry × 1.30
STOP_LOSS = 0.15            # 止: sold when the day's low reaches entry × 0.85
MAX_DAYS = 20               # 期: sold at the close 20 trading days after the entry day (short-term)


def exits(bars: pd.DataFrame, sig: pd.DataFrame, take_profit: float = TAKE_PROFIT,
          stop_loss: float = STOP_LOSS, max_days: int = MAX_DAYS) -> pd.DataFrame:
    """Each signal's trade by the backtested rule: bought at the next day's open, all of it; sold,
    all of it, at whichever comes first (from the day after the entry: T+1):
      止  the day's low at or under entry × (1 − stop_loss): at that price, or the open if it gapped under
      盈  the day's high at or over entry × (1 + take_profit): at that price, or the open if it gapped over
      期  max_days trading days after the entry day: at that day's close
      卖  a sell / avoid signal (卖): at the next day's open
    A day that touches both the stop and the target counts as the stop. Still open (持有中) while none
    has come. Returns are on adjusted prices (a dividend is no loss), before costs; prices shown are
    the day's unadjusted ones."""
    x = indicators(bars)
    dates = x["date"].tolist()
    C, opn, close = x["close_adj"].to_numpy(), x["open_adj"].to_numpy(), x["close"].to_numpy()
    fac = close / C                                  # adjusted → the day's price
    bh = bars.reset_index(drop=True)
    adj = C / close
    H = bh["high"].to_numpy(dtype=float) * adj
    L = bh["low"].to_numpy(dtype=float) * adj
    sell = _sell_condition(x).to_numpy()
    rows = []
    for d in sig["date"]:
        i = dates.index(d)
        if i + 1 >= len(dates) or np.isnan(opn[i + 1]):
            rows.append({"date": d, "entry_date": None, "exit_date": None, "sell_date": None, "exit": "待买入",
                         "ret": None, "days": 0})
            continue
        e = opn[i + 1]
        stop, target = e * (1 - stop_loss), e * (1 + take_profit)
        entry = {"date": d, "entry_date": dates[i + 1], "entry_price": round(float(e * fac[i + 1]), 2),
                 "target_price": round(float(target * fac[i + 1]), 2), "stop_price": round(float(stop * fac[i + 1]), 2)}
        out = None
        for k in range(i + 1, len(dates)):
            held = k - (i + 1)
            if np.isnan(C[k]):
                continue
            if held >= 1 and L[k] <= stop:
                out = ("止", k, opn[k] if opn[k] <= stop else stop, None)
                break
            if held >= 1 and H[k] >= target:
                out = ("盈", k, opn[k] if opn[k] >= target else target, None)
                break
            if held >= max_days:
                out = ("期", k, C[k], None)
                break
            if sell[k] and k + 1 < len(dates) and not np.isnan(opn[k + 1]):
                out = ("卖", k + 1, opn[k + 1], dates[k])
                break
        last = (out[1] if out else len(dates) - 1)
        seg = C[i + 1:last + 1]
        m = int(np.nanargmax(seg)) if len(seg) and not np.isnan(seg).all() else None
        peak = {"peak_date": dates[i + 1 + m] if m is not None else None,
                "peak_ret": round((seg[m] / e - 1) * 100, 2) if m is not None else None}
        if out is None:
            n = len(dates) - 1
            rows.append({**entry, "exit_date": None, "sell_date": None, "exit": "持有中",
                         "ret": round((C[n] / e - 1) * 100, 2), "days": n - (i + 1), **peak})
            continue
        kind, k, px, sell_day = out
        rows.append({**entry, "exit_date": dates[k], "sell_date": sell_day, "exit": kind,
                     "exit_price": round(float(px * fac[k]), 2), "ret": round((px / e - 1) * 100, 2),
                     "days": k - (i + 1), **peak})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 卖出 / 规避 (sell / avoid): what lagged the market most steadily in the same backtest
# ---------------------------------------------------------------------------
SELL_RULE = ("卖出 / 规避信号：① 近 20 个交易日涨幅 > 30%（复权）；或 ② 强上升趋势中的 MACD 金叉——"
             "MACD(12,26,9) 金叉，且 ADX > 25、+DI > −DI，ADX 高于 3 日前。市场条件：全市场 MCL 不高于 3 日前时更弱。")
SELL_STATS = ("全 A 股 2021-01 至 2026-11 回测：信号后 20 日超额 −1.44%（胜率 40%，超额胜率 36%），2021–2026 年每年为负；"
              "市场 MCL 走低时 −1.68%。单项：20 日涨幅 > 30% 为 −1.73%，强上升趋势中 MACD 金叉且 ADX 走高为 −1.02%。"
              "常用的零轴上方死叉（−0.17%）、跌破 MA20（+0.02%）、KDJ 高位死叉（+0.10%）、放量滞涨（+0.10%）都不能可靠地预示下跌。"
              "这是相对大盘的统计，说明之后大概率跑输，不等于一定下跌。")


def sell_signals(bars: pd.DataFrame, market_mcl: pd.Series | None = None, include: set | None = None) -> pd.DataFrame:
    """Each day a sell / avoid signal fired (one per COOLDOWN days, and every day in ``include``: the
    days that close a trade): the 20-day gain over 30%, or a
    MACD golden cross in a strong uptrend with ADX rising; with whether the market was weakening
    (its MCL not above 3 days before; None without the market's series)."""
    x = indicators(bars)
    C = x["close_adj"]
    gain20 = (C / C.shift(20) - 1) * 100
    hot = gain20 > 30
    chase = x["macd_up"] & (x["adx"] > 25) & (x["pdi"] > x["mdi"]) & (x["adx"] > x["adx"].shift(3))
    fired = _sell_condition(x).to_numpy()
    include = include or set()
    dates = x["date"].tolist()
    keep, last = [], -10**9
    for i in np.flatnonzero(fired):
        # The first of a run, and any day that closes a trade (so every sale has its 卖).
        if i - last > COOLDOWN or dates[i] in include:
            keep.append(i)
            if i - last > COOLDOWN:
                last = i
    rows = x.iloc[keep][["date", "close", "adx", "pdi", "mdi"]].copy()
    rows["gain20"] = gain20.iloc[keep].to_numpy()
    rows["reason"] = ["、".join(r for r, c in ((f"20 日涨幅 {g:+.1f}%", h), ("强上升趋势中 MACD 金叉（ADX 走高）", c)) if c)
                      for g, h, c in zip(gain20.iloc[keep], hot.iloc[keep], chase.iloc[keep], strict=True)]
    if market_mcl is not None and len(market_mcl):
        m = market_mcl.sort_index()
        up = (m > m.shift(3)).where(m.shift(3).notna())
        flags = [None if d not in up.index or pd.isna(up[d]) else not bool(up[d]) for d in rows["date"]]
    else:
        flags = [None] * len(rows)
    rows["market_weak"] = pd.Series(flags, index=rows.index, dtype=object)
    return rows.reset_index(drop=True)


def setup_now(bars: pd.DataFrame) -> dict:
    """The latest day's readings: is the setup in place, and which parts are missing."""
    xs = indicators(bars)
    x = xs.iloc[-1]
    gain20 = (xs["close_adj"].iloc[-1] / xs["close_adj"].iloc[-21] - 1) * 100 if len(xs) > 20 else None
    return {"date": x["date"], "adx": x["adx"], "pdi": x["pdi"], "mdi": x["mdi"], "pctb": x["pctb"],
            "wr10": x["wr10"], "rsi6": x["rsi6"], "dif": x["dif"],
            "downtrend": bool(x["adx"] > 25 and x["mdi"] > x["pdi"]),
            "oversold": bool(x["pctb"] < 0 or x["wr10"] > 80 or x["rsi6"] < 20),
            "gain20": gain20, "uptrend": bool(x["adx"] > 25 and x["pdi"] > x["mdi"])}
