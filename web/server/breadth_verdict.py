"""市场广度综合研判: one reading of the breadth indicators, built up in three steps.

  ① 定趋势  腾落线 (its 20-day change) and MSI (its sign and its 5-day direction): which way the
            market's insides are going;
  ② 找时机  MCL (its sign and 5-day direction), the breadth thrust (a signal in the last 20 days,
            or the low zone) and ADR (its 10-day average's percentile): is a turn showing;
  ③ 验真伪  TRIN (its 10-day percentile) and 腾落线 against the index (中证全指) over 20 days: is the
            move real.
  当日结构  the day's breadth (涨家占比 / ADL), money (TRIN_额 / TRIN_量) and MCL together: 普涨,
            少数股抱团, 抱团瓦解, 无差别下跌 … (STRUCTURES), each with what followed it here.

Every indicator's state is judged by what followed it here, not by a textbook threshold: the
days in the past with the same state, and how the 中证全指 did over the next 5 and 20 trading
days, against all days. Only days whose 20 days had passed by the day asked about are counted,
so a past day's reading uses nothing it could not have known. A state is 偏多 / 偏空 when both its
5- and 20-day rise rates beat / trail the baseline by EDGE points (短期偏多 / 偏空 when only the
5-day one does), else 中性; under MIN_DAYS days it is said to be thin.

A-shares often run against the textbook here (a broad fall is followed by more falls in the
short run, an oversold ADR does not bounce, a strongly broad market keeps going), which is why
the history decides. It is a summary of what happened, not a forecast.
"""
from __future__ import annotations

import threading

import numpy as np
import pandas as pd

from tradingagents.dataflows.vendors.akshare import settings as ak_settings, store
from web.server import breadth, market

EDGE = 5.0              # points of rise rate over the baseline for a lean
MIN_DAYS = 30           # fewer like days: said to be thin
HORIZONS = (5, 20)
_lock = threading.Lock()
_MEMO: dict[str, pd.Series] = {}


def _csi_all_daily(start: str) -> pd.DataFrame:
    """中证全指 daily bars from ``start``: Eastmoney, else 中证指数公司 itself (Sina's copy of this
    index stopped in 2016, so it is no fallback here)."""
    try:
        return store.ak().stock_zh_index_daily_em(symbol="sh000985", start_date=start)
    except Exception:  # noqa: BLE001 — Eastmoney rate-limits
        end = store.now_cst().strftime("%Y%m%d")
        df = store.ak().stock_zh_index_hist_csindex(symbol="000985", start_date=start, end_date=end)
        return pd.DataFrame({"date": df["日期"], "close": pd.to_numeric(df["收盘"], errors="coerce")})


def index_closes(fetch=None) -> pd.Series:
    """date -> 中证全指 close, the data sync's ``ts/csi_all`` kept up to date (once a closed day)."""
    day = market.last_closed_day()
    with _lock:
        if day not in _MEMO:
            df = (fetch or (lambda: store.incremental("csi_all", _csi_all_daily, "date", ak_settings.START_DATE)))()
            s = pd.Series(pd.to_numeric(df["close"], errors="coerce").to_numpy(),
                          index=store.to_local_dates(df["date"]).dt.strftime("%Y-%m-%d"))
            _MEMO.clear()
            _MEMO[day] = s[~s.index.duplicated(keep="last")].sort_index().dropna()
        return _MEMO[day]


# 当日市场结构: breadth by 涨家占比 (≥ 60% broad rise, ≤ 40% broad fall), the money by TRIN_额
# (< 0.8 with the rising stocks, > 1.2 with the falling ones), a cluster breaking up by TRIN_额
# climbing 0.2 or more off its lowest of the 3 days before into the balanced band on a broad
# fall, MCL for momentum.
BROAD_UP, BROAD_DOWN, TRIN_LOW, TRIN_HIGH, TRIN_RISE = 60.0, 40.0, 0.8, 1.2, 0.2
STRUCTURES = (
    ("broad_up_strong", "普涨（健康）", f"涨家占比 ≥ {BROAD_UP:.0f}%，TRIN_额 ≤ {TRIN_HIGH}，MCL > 0",
     "多数股票上涨，资金没有流向下跌股，广度动能向上：上涨面广、有资金和动能支撑"),
    ("broad_up_rebound", "普涨反弹", f"涨家占比 ≥ {BROAD_UP:.0f}%，TRIN_额 ≤ {TRIN_HIGH}，MCL ≤ 0",
     "当天普涨，但广度动能仍向下：多为超跌后的反弹，需看能否持续"),
    ("fake_up", "虚涨（资金在跌）", f"涨家占比 ≥ {BROAD_UP:.0f}%，TRIN_额 > {TRIN_HIGH}",
     "上涨家数多，但成交集中在下跌股：涨的多是小票，资金在撤"),
    ("cluster_hold", "少数股抱团", f"涨家占比 ≤ {BROAD_DOWN:.0f}%，TRIN_额 < {TRIN_LOW}",
     "多数股票下跌，资金集中在少数上涨股：抱团行情，指数可能被少数权重撑住"),
    ("cluster_break", "抱团瓦解", f"涨家占比 ≤ {BROAD_DOWN:.0f}%，TRIN_额 {TRIN_LOW}–{TRIN_HIGH} 且比前 3 日最低升 ≥ {TRIN_RISE}",
     "抱团股也开始被卖，资金不再集中：正从抱团走向无差别下跌"),
    ("broad_down", "无差别下跌", f"涨家占比 ≤ {BROAD_DOWN:.0f}%，TRIN_额 {TRIN_LOW}–{TRIN_HIGH}",
     "多数股票下跌，资金也没有躲进上涨股：普跌，没有避风港"),
    ("panic", "恐慌普跌", f"涨家占比 ≤ {BROAD_DOWN:.0f}%，TRIN_额 > {TRIN_HIGH}",
     "普跌且成交集中在下跌股：恐慌性抛售，常出现在急跌末段"),
    ("mixed_cluster", "分化·资金集中", f"涨家占比 {BROAD_DOWN:.0f}–{BROAD_UP:.0f}%，TRIN_额 < {TRIN_LOW}",
     "涨跌家数相近，资金偏向上涨股：结构性行情"),
    ("mixed", "分化·均衡", f"涨家占比 {BROAD_DOWN:.0f}–{BROAD_UP:.0f}%，TRIN_额 {TRIN_LOW}–{TRIN_HIGH}",
     "涨跌和资金都相对均衡：方向不明的震荡"),
    ("mixed_out", "分化·资金流出", f"涨家占比 {BROAD_DOWN:.0f}–{BROAD_UP:.0f}%，TRIN_额 > {TRIN_HIGH}",
     "涨跌家数相近，资金偏向下跌股：资金在撤，偏弱的震荡"),
)


def structure_states(up_pct: pd.Series, trin: pd.Series, trin3: pd.Series, mcl: pd.Series) -> pd.Series:
    """Each day's 当日市场结构 (a key of STRUCTURES; "" without the readings)."""
    up, down = up_pct >= BROAD_UP, up_pct <= BROAD_DOWN
    mid = ~up & ~down
    low, high = trin < TRIN_LOW, trin > TRIN_HIGH
    balanced = ~low & ~high
    rising = trin3 >= TRIN_RISE
    ok = up_pct.notna() & trin.notna()
    keys = np.select([
        up & ~high & (mcl > 0), up & ~high, up & high,
        down & low, down & balanced & rising, down & balanced, down & high,
        mid & low, mid & balanced, mid & high,
    ], [k for k, *_ in STRUCTURES], "")
    return pd.Series(np.where(ok, keys, ""), index=up_pct.index)


def frame(table: pd.DataFrame, stats: pd.DataFrame, idx: pd.Series) -> pd.DataFrame:
    """Each day's readings, states and the 中证全指's change over the next 5 and 20 days."""
    st = stats.set_index("date").reindex(table.index)
    adl = (st["up"] - st["down"]).cumsum()
    close = idx.reindex(table.index).ffill()
    if len(idx):
        close[close.index > idx.index[-1]] = np.nan      # no index yet for those days: not a stale one
    d = pd.DataFrame(index=table.index)
    d["adl"] = adl
    d["adl20"] = adl.diff(20)
    d["idx20"] = close.pct_change(20, fill_method=None) * 100
    d["msi"], d["msi5"] = table["mcl_sum"], table["mcl_sum"].diff(5)
    d["mcl"], d["mcl5"] = table["mcl_osc"], table["mcl_osc"].diff(5)
    d["thrust"] = table["thrust"]
    sig = table["thrust_signal"].fillna(False).astype(bool)
    d["sig20"] = sig.astype(int).rolling(20, min_periods=1).max().astype(bool)
    d["last_sig"] = pd.Series(np.where(sig, table.index, None), index=table.index).ffill()
    d["adr10"], d["adr_r"] = table["adr10"], table["adr10_rank"]
    d["trin10"], d["trin_r"] = table["trin_amt10"], table["trin_amt10_rank"]
    for h in HORIZONS:
        d[f"f{h}"] = (close.shift(-h) / close - 1) * 100
    d["adl_state"] = np.select([d.adl20 > 0, d.adl20 < 0], ["up", "down"], "")
    d["msi_state"] = np.select([(d.msi > 0) & (d.msi5 >= 0), (d.msi > 0) & (d.msi5 < 0),
                                (d.msi < 0) & (d.msi5 > 0), d.msi < 0], ["pos_up", "pos_down", "neg_up", "neg_down"], "")
    d["mcl_state"] = np.select([(d.mcl > 0) & (d.mcl5 >= 0), (d.mcl > 0) & (d.mcl5 < 0),
                                (d.mcl < 0) & (d.mcl5 > 0), d.mcl < 0], ["pos_up", "pos_down", "neg_up", "neg_down"], "")
    d["thrust_state"] = np.select([d.sig20, d.thrust < breadth.THRUST_LOW, d.thrust > breadth.THRUST_HIGH],
                                  ["signal", "low", "high"], np.where(d.thrust.notna(), "mid", ""))
    d["adr_state"] = np.select([d.adr_r <= 10, d.adr_r >= 90], ["oversold", "hot"], np.where(d.adr_r.notna(), "normal", ""))
    d["trin_state"] = np.select([d.trin_r >= 80, d.trin_r <= 20], ["to_falling", "to_rising"], np.where(d.trin_r.notna(), "normal", ""))
    # 当日市场结构: the day's breadth (涨家占比, ADL's day change), where the money went (TRIN_额,
    # TRIN_量 to confirm), TRIN's move over 3 days, and MCL.
    d["up_pct"], d["adl_day"] = table["up_pct"], st["up"] - st["down"]
    d["n_up"], d["n_down"], d["n_flat"] = st["up"], st["down"], st["flat"]
    d["limit_up"], d["limit_down"] = st.get("limit_up"), st.get("limit_down")
    d["up_amt_pct"], d["amt_gap"] = table.get("up_amt_pct"), table.get("amt_gap")
    d["vol_gap"], d["amount"] = table.get("vol_gap"), st.get("amount")
    d["trin_amt"], d["trin_vol"] = table["trin_amt"], table["trin_vol"]
    # How far TRIN_额 has climbed off its lowest of the 3 days before: a cluster breaking up.
    d["trin3"] = table["trin_amt"] - table["trin_amt"].shift(1).rolling(3, min_periods=1).min()
    d["structure"] = structure_states(d["up_pct"], d["trin_amt"], d["trin3"], d["mcl"])
    d["div_state"] = np.select([(d.idx20 > 0) & (d.adl20 < 0), (d.idx20 < 0) & (d.adl20 > 0),
                                (d.idx20 > 0) & (d.adl20 > 0), (d.idx20 < 0) & (d.adl20 < 0)],
                               ["fake_up", "fake_down", "real_up", "real_down"], "")
    return d


def _stats(hist: pd.DataFrame, mask: pd.Series) -> dict:
    x = hist[mask]
    out = {"days": int(len(x))}
    for h in HORIZONS:
        f = x[f"f{h}"]
        out[f"up{h}"] = round(float((f > 0).mean() * 100), 1) if len(f) else None
        out[f"avg{h}"] = round(float(f.mean()), 2) if len(f) else None
    return out


def _lean(s: dict, base: dict) -> tuple[str, float]:
    """(偏多 / 短期偏多 / 中性 / 短期偏空 / 偏空, a score: the rise rates' lead over the baseline)."""
    if not s["days"] or s["up5"] is None:
        return "无历史可比", 0.0
    d5, d20 = s["up5"] - base["up5"], s["up20"] - base["up20"]
    score = (d5 + d20) / 2
    if d5 >= EDGE and d20 >= EDGE:
        lean = "偏多"
    elif d5 <= -EDGE and d20 <= -EDGE:
        lean = "偏空"
    elif d5 >= EDGE:
        lean = "短期偏多"
    elif d5 <= -EDGE:
        lean = "短期偏空"
    else:
        lean = "中性"
    return lean, round(score, 1)


def _history(s: dict, base: dict) -> str:
    thin = "（样本少，仅供参考）" if s["days"] < MIN_DAYS else ""
    return (f"历史上同类状态 {s['days']} 天：后 5 日上涨概率 {s['up5']}%（基准 {base['up5']}%）、"
            f"平均 {s['avg5']:+.2f}%；后 20 日 {s['up20']}%（基准 {base['up20']}%）、平均 {s['avg20']:+.2f}%{thin}")


ADL_TEXT = {"up": "腾落线近 20 日上升：多数股票在涨，内部在变好", "down": "腾落线近 20 日下降：多数股票在跌，内部在变坏"}
MSI_TEXT = {"pos_up": "MSI 在 0 轴上方且仍在上升：中期广度强、还在增强", "pos_down": "MSI 在 0 轴上方但近 5 日回落：中期偏强、动能在减弱",
            "neg_up": "MSI 在 0 轴下方但近 5 日回升：中期偏弱、开始止跌", "neg_down": "MSI 在 0 轴下方且仍在下降：中期广度承压、还在恶化"}
MCL_TEXT = {"pos_up": "MCL 在 0 轴上方且上升：广度动能向上、在加速", "pos_down": "MCL 在 0 轴上方但回落：上涨动能在衰减",
            "neg_up": "MCL 在 0 轴下方但回升：下跌动能在衰减，可能接近转折", "neg_down": "MCL 在 0 轴下方且继续走低：下跌动能仍在加强"}
THRUST_TEXT = {"signal": "近 20 日出现过广度推力信号：从普跌到普涨的爆发性反转", "low": "广度推力在 0.40 以下的低位区：普跌、尚无推力",
               "high": "广度推力在 0.615 以上：普涨爆发中", "mid": "广度推力在中性区：无极端"}
ADR_TEXT = {"oversold": "ADR 10 日均处于近一年最低 10% 分位：极度超跌", "hot": "ADR 10 日均处于近一年最高 10% 分位：普涨强势",
            "normal": "ADR 10 日均处于常态区间"}
TRIN_TEXT = {"to_falling": "TRIN 10 日均处于近一年最高 20% 分位：资金更多流向下跌股", "to_rising": "TRIN 10 日均处于近一年最低 20% 分位：资金集中在少数上涨股",
             "normal": "TRIN 10 日均处于常态区间"}
DIV_TEXT = {"fake_up": "指数近 20 日上涨而腾落线下降：少数权重股拉指数，「虚涨」", "fake_down": "指数近 20 日下跌而腾落线上升：多数股票抗跌，「假跌」",
            "real_up": "指数与腾落线近 20 日同涨：上涨有广度支撑，「真涨」", "real_down": "指数与腾落线近 20 日同跌：下跌是普跌，「真跌」"}


ROWS = (("定趋势", "腾落线 ADL", "adl_state"), ("定趋势", "MSI 麦克莱伦累积指数", "msi_state"),
        ("找时机", "MCL 麦克连指标", "mcl_state"), ("找时机", "广度推力", "thrust_state"), ("找时机", "涨跌比 ADR", "adr_state"),
        ("验真伪", "TRIN 阿姆氏指标", "trin_state"), ("验真伪", "腾落线 × 指数（背离）", "div_state"))
WEIGHTS = {"定趋势": 0.3, "找时机": 0.3, "验真伪": 0.4}   # the confirming step, the most reliable here, weighs most


def _past(d: pd.DataFrame, pos: int) -> pd.DataFrame:
    """The days before ``pos`` whose 20 days had passed by it (after a 60-day warm-up)."""
    return d.iloc[60:max(pos - max(HORIZONS) + 1, 60)].dropna(subset=[f"f{h}" for h in HORIZONS])


def _lead(rows: list[dict], base: dict, h: int) -> float:
    """The rows' rise-rate lead over the baseline at horizon ``h``, weighted by step and sample."""
    num = den = 0.0
    for r in rows:
        if r["history"] and r["history"][f"up{h}"] is not None:
            w = WEIGHTS[r["step"]] * min(r["history"]["days"], 100) / 100
            num += w * (r["history"][f"up{h}"] - base[f"up{h}"])
            den += w
    return round(num / den, 1) if den else 0.0


def _word(x: float) -> str:
    return "偏多" if x >= EDGE else "偏空" if x <= -EDGE else "略偏多" if x >= EDGE / 2 else "略偏空" if x <= -EDGE / 2 else "中性"


def _judge(d: pd.DataFrame, pos: int) -> dict | None:
    """Day ``pos``'s states, each judged by the days before it: rows (step, name, state, lean,
    score, history), the baseline, and the short and medium leads; None without enough past."""
    hist = _past(d, pos)
    if len(hist) < MIN_DAYS:
        return None
    now = d.iloc[pos]
    base = _stats(hist, pd.Series(True, index=hist.index))
    rows = []
    for step, name, col in ROWS:
        state = now[col]
        if not state:
            rows.append({"step": step, "name": name, "state": None, "lean": "无数据", "score": 0.0, "history": None})
            continue
        st = _stats(hist, hist[col] == state)
        lean, score = _lean(st, base)
        rows.append({"step": step, "name": name, "state": state, "lean": lean, "score": score, "history": st})
    short, mid = _lead(rows, base, 5), _lead(rows, base, 20)
    return {"hist": hist, "base": base, "rows": rows, "short": short, "mid": mid}


def verdict(date: str | None = None, table=None, stats=None, idx=None) -> dict:
    """The breadth indicators' states on ``date``, each judged by its history, and the reading
    built up from them: trend, then timing, then whether the move is real."""
    days = market._days_on_record(date)
    day = days[-1]
    if table is None:
        table = breadth._table(breadth._key())
    if stats is None:
        stats, _ = market._span_stats(list(table.index))
    if idx is None:
        idx = index_closes()
    d = frame(table, stats, idx)
    if day not in d.index:
        raise FileNotFoundError(f"no breadth figures for {day}")
    now = d.loc[day]
    pos = d.index.get_loc(day)
    judged = _judge(d, pos)
    if judged is None:
        raise FileNotFoundError(f"not enough history before {day} to judge by")
    hist, base = judged["hist"], judged["base"]

    def row(step, name, col, texts, reading):
        state = now[col]
        if not state:
            return {"step": step, "name": name, "reading": reading, "state": None, "lean": "无数据", "score": 0.0,
                    "reason": "当日读数不足", "history": None}
        s = _stats(hist, hist[col] == state)
        lean, score = _lean(s, base)
        return {"step": step, "name": name, "reading": reading, "state": state, "lean": lean, "score": score,
                "reason": f"{texts[state]}。{_history(s, base)}", "history": s}

    f = lambda v, fmt: "—" if v is None or (isinstance(v, float) and np.isnan(v)) else format(v, fmt)  # noqa: E731
    rows = [
        row("定趋势", "腾落线 ADL", "adl_state", ADL_TEXT, f"近 20 日净 {f(now.adl20, '+,.0f')} 家"),
        row("定趋势", "MSI 麦克莱伦累积指数", "msi_state", MSI_TEXT, f"{f(now.msi, '.0f')}（5 日 {f(now.msi5, '+.0f')}）"),
        row("找时机", "MCL 麦克连指标", "mcl_state", MCL_TEXT, f"{f(now.mcl, '.1f')}（5 日 {f(now.mcl5, '+.1f')}）"),
        row("找时机", "广度推力", "thrust_state", THRUST_TEXT,
            f"{f(now.thrust, '.3f')}" + (f"，信号 {now.last_sig}" if now.sig20 and isinstance(now.last_sig, str) else "")),
        row("找时机", "涨跌比 ADR", "adr_state", ADR_TEXT, f"10 日均 {f(now.adr10, '.2f')}（{f(now.adr_r, '.0f')}% 分位）"),
        row("验真伪", "TRIN 阿姆氏指标", "trin_state", TRIN_TEXT, f"10 日均 {f(now.trin10, '.2f')}（{f(now.trin_r, '.0f')}% 分位）"),
        row("验真伪", "腾落线 × 指数（背离）", "div_state", DIV_TEXT, f"指数 {f(now.idx20, '+.2f')}%，腾落线 {f(now.adl20, '+,.0f')} 家"),
    ]

    def step_sum(step: str) -> dict:
        rs = [r for r in rows if r["step"] == step and r["history"]]
        w = [min(r["history"]["days"], 100) for r in rs]
        score = round(sum(r["score"] * x for r, x in zip(rs, w, strict=False)) / sum(w), 1) if sum(w) else 0.0
        return {"score": score, "lean": "偏多" if score >= EDGE else "偏空" if score <= -EDGE else "中性"}

    trend, timing, check = step_sum("定趋势"), step_sum("找时机"), step_sum("验真伪")
    # ① direction of the insides, as the textbook reads it, and what followed such days here
    up_votes = sum(1 for c in ("adl_state", "msi_state") if str(now[c]).startswith(("up", "pos")))
    trend["text"] = {2: "腾落线与 MSI 都向上：市场内部在变好", 0: "腾落线与 MSI 都向下：市场内部在变坏"}.get(
        up_votes, "腾落线与 MSI 方向不一：内部趋势分歧") + f"；按本地历史，这类组合后市{trend['lean']}（得分 {trend['score']:+.1f}）。"
    # ② turns: which of MCL, the thrust and ADR are showing one
    turns = []
    if now.mcl_state == "neg_up":
        turns.append("MCL 下跌动能衰减")
    if now.mcl_state == "pos_down":
        turns.append("MCL 上涨动能衰减")
    if now.msi_state == "neg_up":
        turns.append("MSI 止跌回升")
    if now.msi_state == "pos_down":
        turns.append("MSI 高位回落")
    if now.thrust_state == "signal":
        turns.append("出现广度推力")
    timing["text"] = ("出现转折迹象：" + "、".join(turns) if turns else "暂无转折迹象：动能仍沿原方向") + \
        f"；按本地历史，找时机各项合计后市{timing['lean']}（得分 {timing['score']:+.1f}）。"
    # ③ is it real: TRIN and the divergence
    check["text"] = f"{DIV_TEXT.get(now.div_state, '指数与腾落线无明显关系')}；{TRIN_TEXT.get(now.trin_state, 'TRIN 无数据')}" + \
        f"；按本地历史后市{check['lean']}（得分 {check['score']:+.1f}）。"
    # The whole: short (5 days) and medium (20 days) separately (``_lead``), the same three-step
    # state's own history beside it.
    short, mid = judged["short"], judged["mid"]
    word = _word
    joint = _stats(hist, (hist["adl_state"] == now.adl_state) & (hist["mcl_state"].str[:3] == str(now.mcl_state)[:3])
                   & (hist["div_state"] == now.div_state))
    # What to watch for: the turns that have counted here, as the trend now stands.
    def watch(label: str, mask: pd.Series) -> dict:
        x = _stats(hist, mask)
        return {"signal": label, **x}
    if up_votes <= 1:
        watches = [watch("MSI 在 0 轴下方回升（5 日）", (hist.msi < 0) & (hist.msi5 > 0)),
                   watch("MCL 在 0 轴下方回升（5 日）", (hist.mcl < 0) & (hist.mcl5 > 0)),
                   watch("广度推力信号（近 20 日）", hist.sig20),
                   watch("ADR 10 日均升至近一年最高 10% 分位", hist.adr_r >= 90)]
    else:
        watches = [watch("指数涨而腾落线跌（虚涨）", (hist.idx20 > 0) & (hist.adl20 < 0)),
                   watch("TRIN 10 日均升至近一年最高 20% 分位", hist.trin_r >= 80),
                   watch("MCL 在 0 轴上方回落（5 日）", (hist.mcl > 0) & (hist.mcl5 < 0))]
    headline = f"短期（5 日）{word(short)}，中期（20 日）{word(mid)}。"
    points = [f"①趋势：{trend['text'].split('；')[0]}",
              f"②时机：{timing['text'].split('；')[0]}",
              f"③验真伪：{DIV_TEXT.get(now.div_state, '指数数据不足').split('：')[-1]}，"
              f"{TRIN_TEXT.get(now.trin_state, 'TRIN 无数据').split('：')[-1]}"]
    summary = headline + "；".join(points) + "。"
    # 当日市场结构: every state with its rule, meaning and what followed it here; today's marked.
    structure = {
        "state": now["structure"] or None,
        "readings": {"up": None if pd.isna(now.n_up) else int(now.n_up), "down": None if pd.isna(now.n_down) else int(now.n_down),
                     "flat": None if pd.isna(now.n_flat) else int(now.n_flat),
                     "limit_up": None if pd.isna(now.limit_up) else int(now.limit_up),
                     "limit_down": None if pd.isna(now.limit_down) else int(now.limit_down),
                     "up_amt_pct": None if pd.isna(now.up_amt_pct) else round(float(now.up_amt_pct), 2),
                     "amt_gap": None if pd.isna(now.amt_gap) else round(float(now.amt_gap), 2),
                     "adl_day": None if pd.isna(now.adl_day) else int(now.adl_day),
                     "up_pct": None if pd.isna(now.up_pct) else round(float(now.up_pct), 2),
                     "trin_amt": None if pd.isna(now.trin_amt) else round(float(now.trin_amt), 3),
                     "trin_vol": None if pd.isna(now.trin_vol) else round(float(now.trin_vol), 3),
                     "trin3": None if pd.isna(now.trin3) else round(float(now.trin3), 3),
                     "mcl": None if pd.isna(now.mcl) else round(float(now.mcl), 1)},
        "rows": [{"key": k, "label": label, "rule": rule, "meaning": meaning, "today": k == now["structure"],
                  **_stats(hist, hist["structure"] == k)} for k, label, rule, meaning in STRUCTURES],
    }
    return {
        "date": day, "index_date": idx.index[-1] if len(idx) else None, "baseline": base,
        "history_from": hist.index[0], "history_to": hist.index[-1], "rows": rows, "structure": structure,
        "steps": {"trend": trend, "timing": timing, "check": check},
        "conclusion": {"short": short, "short_word": word(short), "mid": mid, "mid_word": word(mid),
                       "joint": joint, "summary": summary, "headline": headline, "points": points, "watch": watches,
                       "text": f"① {trend['text']} ② {timing['text']} ③ {check['text']}"},
    }


STRUCTURE_RANGES = {"1d": 1, "10d": 10, "30d": 30, "60d": 60, "6m": None}


def structure_days(end: str | None = None, rng: str = "10d", table=None, stats=None) -> dict:
    """当日市场结构 day by day over ``rng`` (1d / 10d / 30d / 60d trading days, or 6m) to ``end``:
    each day's counts, limit moves, 涨家 / 涨额占比, 额价差, 量价差, MCL, TRIN_额 / TRIN_量, the
    amount traded and the structure it reads as; the newest day first."""
    if rng not in STRUCTURE_RANGES:
        raise ValueError(f"range must be one of {', '.join(STRUCTURE_RANGES)}")
    days = market._days_on_record(end)
    end = days[-1]
    if table is None:
        table = breadth._table(breadth._key())
    if stats is None:
        stats, _ = market._span_stats(list(table.index))
    d = frame(table, stats, pd.Series(dtype=float))
    d = d[d.index <= end]
    n = STRUCTURE_RANGES[rng]
    d = d.tail(n) if n else d[d.index >= market._range_start(end, rng, days)]
    label = {k: lab for k, lab, *_ in STRUCTURES}

    def num(v, nd: int):
        return None if v is None or pd.isna(v) else round(float(v), nd)

    def whole(v):
        return None if v is None or pd.isna(v) else int(v)
    out = [{"date": day, "up": whole(r.n_up), "down": whole(r.n_down), "flat": whole(r.n_flat),
            "limit_up": whole(r.limit_up), "limit_down": whole(r.limit_down),
            "up_pct": num(r.up_pct, 2), "up_amt_pct": num(r.up_amt_pct, 2), "amt_gap": num(r.amt_gap, 2),
            "vol_gap": num(r.vol_gap, 2), "mcl": num(r.mcl, 1), "trin_amt": num(r.trin_amt, 3), "trin_vol": num(r.trin_vol, 3),
            "amount": num(r.amount, 0), "adl_day": whole(r.adl_day), "structure": r.structure or None,
            "structure_label": label.get(r.structure)} for day, r in d.iloc[::-1].iterrows()]
    return {"range": rng, "end": end, "days": out}


def history(end: str | None = None, rng: str = "6m", table=None, stats=None, idx=None) -> dict:
    """The reading the card would have given on each trading day of ``rng`` to ``end`` (each day
    judged only by what was known on it), what the 中证全指 then did over 5 and 20 days, and how
    often a 偏多 / 偏空 reading was right."""
    if rng not in market.STATS_RANGES:
        raise ValueError(f"range must be one of {', '.join(market.STATS_RANGES)}")
    days = market._days_on_record(end)
    end = days[-1]
    start = market._range_start(end, rng, days)
    if table is None:
        table = breadth._table(breadth._key())
    if stats is None:
        stats, _ = market._span_stats(list(table.index))
    if idx is None:
        idx = index_closes()
    d = frame(table, stats, idx)
    close = idx.reindex(d.index)
    out = []
    last = d.index.get_loc(end) if end in d.index else len(d) - 1
    for day in d.index[(d.index >= start) & (d.index <= end)]:
        pos = d.index.get_loc(day)
        j = _judge(d, pos)
        if j is None:
            continue
        r = d.loc[day]
        # An outcome only once its window had ended by ``end``: as of that day, nothing later.
        f5 = r["f5"] if pos + 5 <= last else np.nan
        f20 = r["f20"] if pos + 20 <= last else np.nan
        out.append({
            "date": day, "close": None if pd.isna(close.get(day)) else round(float(close[day]), 2),
            "short": j["short"], "short_word": _word(j["short"]), "mid": j["mid"], "mid_word": _word(j["mid"]),
            "leans": {x["name"]: x["lean"] for x in j["rows"]},
            "steps": {s_: round(sum(x["score"] for x in j["rows"] if x["step"] == s_) /
                                max(1, sum(1 for x in j["rows"] if x["step"] == s_)), 1) for s_ in WEIGHTS},
            "f5": None if pd.isna(f5) else round(float(f5), 2), "f20": None if pd.isna(f20) else round(float(f20), 2),
        })

    def hits(key: str, word_key: str) -> dict:
        res = {}
        for side, words, good in (("bull", ("偏多", "略偏多"), lambda v: v > 0), ("bear", ("偏空", "略偏空"), lambda v: v < 0)):
            xs = [x[key] for x in out if x[word_key] in words and x[key] is not None]
            res[side] = {"days": len(xs), "right": sum(1 for v in xs if good(v)),
                         "rate": round(sum(1 for v in xs if good(v)) / len(xs) * 100, 1) if xs else None,
                         "avg": round(sum(xs) / len(xs), 2) if xs else None}
        known = [x[key] for x in out if x[key] is not None]
        res["all_up"] = round(sum(1 for v in known if v > 0) / len(known) * 100, 1) if known else None
        return res
    return {"range": rng, "start": start, "end": end, "days": out,
            "accuracy": {"short": hits("f5", "short_word"), "mid": hits("f20", "mid_word")}}


def invalidate() -> None:
    with _lock:
        _MEMO.clear()
