"""China macro indicators for ``get_macro_indicators``, from AKShare.

An indicator named ``china_*`` (or ``cn_*``) is served here; any other goes to
FRED. ``china_overview`` returns the latest reading of every indicator at once.

Sources are Eastmoney's macro tables (NBS, PBoC and customs releases), the LPR
and RRR histories and the China government bond curve. The release-calendar
feeds that carry publication dates and consensus forecasts stopped updating in
2025, so they are not used.

Point in time: Eastmoney gives each reading's period, not its release date. A run
dated today is served every reading the feed holds: whatever is in a live feed has
been published. A past run is served a monthly or quarterly reading only from a
conservative release day after its period (CPI on the 16th of the next month, for
instance), so a backtest never reads a figure before it was out. LPR, RRR and bond
yields carry their own dates. Values are the feed's current ones, so a past run
may see later revisions.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from tradingagents.dataflows.date_window import get_current_date, is_historical
from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError
from tradingagents.dataflows.vendors.akshare import store

DEFAULT_LOOKBACK_DAYS = 365
MAX_ROWS = 24
EVENT_ROWS = 8          # RRR changes listed, whatever the window
PREFIXES = ("china_", "cn_")


@dataclass(frozen=True)
class Spec:
    title: str
    fetch: Callable[[], pd.DataFrame]
    cache: str                       # store.cached name (shared with the market sync where they overlap)
    period_col: str
    columns: dict[str, str]          # source column -> label; the first is the headline
    frequency: str                   # "monthly" | "quarterly" | "daily" | "event"
    release_day: int = 0             # day of the month after the period a past run may read it from
    late_release: dict[int, int] = field(default_factory=dict)  # release month -> later day (holidays)
    note: str = ""
    shape: Callable[[pd.DataFrame], pd.DataFrame] | None = None
    keep: tuple[str, ...] = field(default=())   # extra text columns shown as is


def _ak(name: str, **kwargs) -> Callable[[], pd.DataFrame]:
    return lambda: getattr(store.ak(), name)(**kwargs)


def _unemployment(raw: pd.DataFrame) -> pd.DataFrame:
    raw = raw.assign(item=raw["item"].astype(str).str.strip(), value=pd.to_numeric(raw["value"], errors="coerce"))
    wide = raw.pivot_table(index="date", columns="item", values="value", aggfunc="last").reset_index()
    wide.columns.name = None
    return wide


def _money(raw: pd.DataFrame) -> pd.DataFrame:
    out = raw.copy()
    out["M1-M2剪刀差"] = pd.to_numeric(out["货币(M1)-同比增长"], errors="coerce") - pd.to_numeric(
        out["货币和准货币(M2)-同比增长"], errors="coerce")
    return out


def _bond() -> pd.DataFrame:
    from tradingagents.dataflows.vendors.akshare import market
    _, fetch, date_col, start = market.market_sources()["bond"]
    return store.incremental("bond", fetch, date_col, start)


SPECS: dict[str, Spec] = {
    "cpi": Spec("China CPI (NBS)", _ak("macro_china_cpi"), "macro_cpi", "月份",
                {"全国-同比增长": "CPI 同比 %", "全国-环比增长": "CPI 环比 %"}, "monthly", 11, late_release={10: 16}),
    "ppi": Spec("China PPI (NBS)", _ak("macro_china_ppi"), "ppi", "月份",
                {"当月同比增长": "PPI 同比 %", "累计": "PPI 累计 (上年同期=100)"}, "monthly", 11,
                late_release={10: 16}),
    "pmi": Spec("China official PMI (NBS)", _ak("macro_china_pmi"), "pmi", "月份",
                {"制造业-指数": "制造业 PMI", "非制造业-指数": "非制造业 PMI"}, "monthly", 1,
                note="50 separates expansion from contraction."),
    "m2": Spec("China money supply (PBoC)", _ak("macro_china_money_supply"), "m_supply", "月份",
               {"货币和准货币(M2)-同比增长": "M2 同比 %", "货币(M1)-同比增长": "M1 同比 %",
                "M1-M2剪刀差": "M1-M2 剪刀差 (pp)", "流通中的现金(M0)-同比增长": "M0 同比 %"}, "monthly", 16,
               note="A widening M1-M2 gap (M1 growing faster) reads as money activating into spending and "
                    "investment; a deeply negative gap as money parked in deposits.",
               shape=_money),
    "new_loans": Spec("China new RMB loans (PBoC)", _ak("macro_china_new_financial_credit"), "macro_credit", "月份",
                      {"当月": "新增人民币贷款 (亿元)", "累计": "年内累计 (亿元)", "累计-同比增长": "累计同比 %"},
                      "monthly", 16, note="Strongly seasonal: compare a month with the same month of earlier years."),
    "tsf": Spec("China total social financing, flow (PBoC)", _ak("macro_china_shrzgm"), "tsf", "月份",
                {"社会融资规模增量": "社融增量 (亿元)", "其中-人民币贷款": "其中人民币贷款 (亿元)",
                 "其中-企业债券": "其中企业债券 (亿元)"}, "monthly", 16,
                note="Strongly seasonal: compare a month with the same month of earlier years."),
    "trade": Spec("China exports and imports (customs)", _ak("macro_china_hgjck"), "macro_trade", "月份",
                  {"当月出口额-同比增长": "出口同比 %", "当月进口额-同比增长": "进口同比 %"}, "monthly", 10,
                  late_release={10: 15}, note="January and February are often released together in March."),
    "industrial_production": Spec("China industrial value added (NBS)", _ak("macro_china_gyzjz"), "macro_ip", "月份",
                                  {"同比增长": "工业增加值 同比 %", "累计增长": "年内累计同比 %"}, "monthly", 20),
    "retail_sales": Spec("China retail sales of consumer goods (NBS)", _ak("macro_china_consumer_goods_retail"),
                         "macro_retail", "月份", {"同比增长": "社零 同比 %", "累计-同比增长": "年内累计同比 %"},
                         "monthly", 20),
    "unemployment": Spec("China surveyed urban unemployment (NBS)", _ak("macro_china_urban_unemployment"),
                         "macro_unemployment", "date",
                         {"全国城镇调查失业率": "城镇调查失业率 %", "全国城镇25—59岁劳动力失业率": "25-59岁 %",
                          "全国城镇外来户籍劳动力失业率": "外来户籍 %"}, "monthly", 20,
                         shape=_unemployment),
    "gdp": Spec("China GDP, real growth (NBS)", _ak("macro_china_gdp"), "macro_gdp", "季度",
                {"国内生产总值-同比增长": "GDP 年内累计同比 %", "第二产业-同比增长": "第二产业 %",
                 "第三产业-同比增长": "第三产业 %"}, "quarterly", 20,
                note="Year-to-date growth: a Q3 row is the first three quarters against the same period a year earlier."),
    "fx_reserves": Spec("China FX and gold reserves (SAFE / PBoC)", _ak("macro_china_fx_gold"), "macro_fx_gold", "月份",
                        {"国家外汇储备-数值": "外汇储备 (亿美元)", "黄金储备-数值": "黄金储备 (万盎司)"}, "monthly", 10),
    "lpr": Spec("China loan prime rate (PBoC)", _ak("macro_china_lpr"), "macro_lpr", "TRADE_DATE",
                {"LPR1Y": "1年期 LPR %", "LPR5Y": "5年期以上 LPR %"}, "event",
                note="Published on the 20th of each month; the 5-year rate anchors mortgages."),
    "rrr": Spec("China reserve requirement ratio (PBoC)", _ak("macro_china_reserve_requirement_ratio"), "macro_rrr",
                "公布时间", {"大型金融机构-调整后": "大型机构 RRR %", "中小金融机构-调整后": "中小机构 RRR %",
                            "大型金融机构-调整幅度": "调整幅度 (pp)"}, "event", keep=("生效时间",),
                note="Dated by announcement (公布时间); 生效时间 is when it took effect."),
    "yields": Spec("China government bond yields", _bond, "", "日期",
                   {"中国国债收益率10年": "10年 %", "中国国债收益率2年": "2年 %", "中国国债收益率5年": "5年 %",
                    "中国国债收益率30年": "30年 %", "中国国债收益率10年-2年": "10年-2年 (pp)"}, "daily"),
}

ALIASES = {
    "inflation": "cpi", "m1": "m2", "money_supply": "m2", "credit": "new_loans", "loans": "new_loans",
    "social_financing": "tsf", "exports": "trade", "imports": "trade", "ip": "industrial_production",
    "industrial_output": "industrial_production", "retail": "retail_sales", "jobless": "unemployment",
    "reserves": "fx_reserves", "rate": "lpr", "loan_prime_rate": "lpr", "reserve_ratio": "rrr",
    "10y": "yields", "10y_bond": "yields", "bond_yield": "yields", "yield_curve": "yields",
    "macro": "overview",
}


def is_china_indicator(indicator) -> bool:
    return isinstance(indicator, str) and indicator.strip().lower().startswith(PREFIXES)


def _key(indicator: str) -> str:
    k = indicator.strip().lower().replace(" ", "_").replace("-", "_")
    for p in PREFIXES:
        if k.startswith(p):
            k = k[len(p):]
            break
    return ALIASES.get(k, k)


# ---------------------------------------------------------------------------
# Periods and release days
# ---------------------------------------------------------------------------
_QUARTER = re.compile(r"(\d{4})年第(?:\d-)?(\d)季度")
_MONTH_CN = re.compile(r"(\d{4})年(\d{1,2})月")
_CN_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


def _period(value, frequency: str) -> pd.Timestamp:
    """The period a row covers (first day of its month or quarter), or its date for daily / event data."""
    s = str(value).strip()
    if frequency == "quarterly":
        m = _QUARTER.search(s)
        return pd.Timestamp(int(m.group(1)), int(m.group(2)) * 3 - 2, 1) if m else pd.NaT
    if frequency == "monthly":
        if m := _MONTH_CN.search(s):
            return pd.Timestamp(int(m.group(1)), int(m.group(2)), 1)
        if re.fullmatch(r"\d{6}", s):
            return pd.Timestamp(int(s[:4]), int(s[4:]), 1)
        return pd.to_datetime(s, errors="coerce")
    if m := _CN_DATE.search(s):
        return pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return pd.to_datetime(s, errors="coerce").normalize()


def _released(period: pd.Timestamp, spec: Spec) -> pd.Timestamp:
    """The day a past run may read a period's figure: ``release_day`` of the month after the period ends."""
    if spec.frequency in ("daily", "event"):
        return period
    months = 3 if spec.frequency == "quarterly" else 1
    after = period + pd.DateOffset(months=months)
    return after.replace(day=max(spec.late_release.get(after.month, spec.release_day), 1))


def _label(period: pd.Timestamp, spec: Spec) -> str:
    if spec.frequency == "quarterly":
        return f"{period.year}Q{(period.month - 1) // 3 + 1}"
    if spec.frequency == "monthly":
        return f"{period:%Y-%m}"
    return f"{period:%Y-%m-%d}"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def _load(spec: Spec) -> pd.DataFrame:
    """Rows with ``_p`` (period) and ``_r`` (readable from), oldest first."""
    try:
        raw = spec.fetch() if not spec.cache else store.cached(spec.cache, lambda: store.call(spec.fetch, spec.title))
    except VendorUnavailableError:
        raise
    except Exception as e:  # noqa: BLE001 — store.cached reports a failed download as RuntimeError
        raise VendorUnavailableError(f"AKShare {spec.title} failed: {str(e)[:200]}") from e
    df = spec.shape(raw) if spec.shape else raw.copy()
    df["_p"] = df[spec.period_col].map(lambda v: _period(v, spec.frequency))
    df = df.dropna(subset=["_p"]).drop_duplicates("_p", keep="first").sort_values("_p")
    df["_r"] = df["_p"].map(lambda p: _released(p, spec))
    return df


def _visible(df: pd.DataFrame, spec: Spec, as_of: str) -> pd.DataFrame:
    """Rows a run dated ``as_of`` could have read."""
    cut = pd.Timestamp(as_of)
    if spec.frequency in ("daily", "event") or not is_historical(as_of):
        return df[df["_p"] <= cut]
    return df[df["_r"] <= cut]


def _stale(df: pd.DataFrame, spec: Spec, as_of: str) -> str | None:
    """A warning when the feed has missed two releases that are due by ``as_of``."""
    if df.empty or spec.frequency == "event":
        return None
    last = df["_p"].iloc[-1]
    cut = pd.Timestamp(as_of)
    if spec.frequency == "daily":
        late = (cut - last).days > 10
    else:
        step = 3 if spec.frequency == "quarterly" else 1
        late = _released(last + pd.DateOffset(months=2 * step), spec) <= cut
    if not late:
        return None
    return (f"Stale source: the latest period is {_label(last, spec)}, and later releases due by {as_of} are "
            "missing from the feed. Treat this series as out of date, not as unchanged.")


def _fmt(v) -> str:
    v = pd.to_numeric(v, errors="coerce")
    if pd.isna(v):
        return "—"
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.2f}"


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def _report(key: str, spec: Spec, as_of: str, look_back_days: int) -> str:
    df = _load(spec)
    cols = [c for c in spec.columns if c in df]
    if not cols:
        raise VendorUnavailableError(f"AKShare {spec.title}: expected columns are missing ({list(spec.columns)})")
    seen = _visible(df, spec, as_of)
    pit = ("readings as the feed holds them" if not is_historical(as_of) or spec.frequency in ("daily", "event")
           else f"a reading is used only from day {spec.release_day} of the month after its period"
                + (" (later after the October holiday)" if spec.late_release else ""))
    head = (f"## China macro: {spec.title} (china_{key})\n"
            f"- Frequency: {spec.frequency}\n- As of: {as_of} ({pit})\n")
    if spec.note:
        head += f"- Note: {spec.note}\n"
    if seen.empty:
        return head + f"\nNo reading of this series was public by {as_of}.\n"
    stale = _stale(seen, spec, as_of)
    if spec.frequency == "event":
        shown = seen.tail(EVENT_ROWS)
    else:
        start = pd.Timestamp(as_of) - pd.Timedelta(days=look_back_days)
        shown = seen[seen["_p"] >= start]
        if shown.empty:
            shown = seen.tail(1)
    cols = [cols[0], *[c for c in cols[1:] if pd.to_numeric(shown[c], errors="coerce").notna().any()]]
    first, last = shown.iloc[0], shown.iloc[-1]
    headline, label = cols[0], spec.columns[cols[0]]
    a, b = pd.to_numeric(first[headline], errors="coerce"), pd.to_numeric(last[headline], errors="coerce")
    out = head + f"\n**Latest:** {label} {_fmt(b)} ({_label(last['_p'], spec)})"
    if len(shown) > 1 and pd.notna(a) and pd.notna(b):
        out += f" | **Change since {_label(first['_p'], spec)}:** {b - a:+.2f} (from {_fmt(a)})"
    out += "\n"
    if stale:
        out += f"\n**{stale}**\n"
    note = ""
    if len(shown) > MAX_ROWS:
        note = f"\n_(showing the most recent {MAX_ROWS} of {len(shown)} readings)_\n"
        shown = shown.tail(MAX_ROWS)
    header = ["Period", *[spec.columns[c] for c in cols], *spec.keep]
    lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    for _, r in shown.iterrows():
        lines.append("| " + " | ".join([_label(r["_p"], spec), *[_fmt(r[c]) for c in cols],
                                        *[str(r.get(k, "")) for k in spec.keep]]) + " |")
    return out + note + "\n" + "\n".join(lines) + "\n"


def _overview(as_of: str) -> str:
    rows, problems = [], []
    for key, spec in SPECS.items():
        try:
            df = _load(spec)
            seen = _visible(df, spec, as_of)
            cols = [c for c in spec.columns if c in seen]
            if seen.empty or not cols:
                problems.append(f"china_{key}: no reading public by {as_of}")
                continue
            last = seen.iloc[-1]
            prev = seen.iloc[-2] if len(seen) > 1 else None
            values = "; ".join(f"{spec.columns[c]} {_fmt(last[c])}" for c in cols[:3])
            before = f"{_fmt(prev[cols[0]])} ({_label(prev['_p'], spec)})" if prev is not None else "—"
            rows.append([f"china_{key}", spec.title, _label(last["_p"], spec), values, before,
                         "STALE" if _stale(seen, spec, as_of) else ""])
        except Exception as e:  # noqa: BLE001 — one failed series must not hide the rest
            problems.append(f"china_{key}: unavailable ({type(e).__name__})")
    if not rows:
        raise VendorUnavailableError(f"AKShare China macro unavailable: {'; '.join(problems)}")
    out = (f"## China macro overview, as of {as_of}\n"
           "Latest public reading of each series; call get_macro_indicators with the series name for its history.\n\n"
           "| Series | Title | Period | Latest | Previous headline | |\n| --- | --- | --- | --- | --- | --- |\n")
    out += "\n".join("| " + " | ".join(r) + " |" for r in rows) + "\n"
    if problems:
        out += "\nNot shown: " + "; ".join(problems) + "\n"
    if any(r[-1] for r in rows):
        out += "\nSTALE: the feed has missed releases due by this date; do not read the value as current.\n"
    return out


def get_macro_data(indicator: str, as_of_date: str | None = None, look_back_days: int | None = None) -> str:
    """A China macro series (``china_cpi``, ``china_pmi`` ...) or ``china_overview``, as of ``as_of_date``."""
    if not is_china_indicator(indicator):
        raise NoMarketDataError(indicator, indicator, "not a China macro indicator (china_*)")
    as_of = as_of_date or get_current_date()
    key = _key(indicator)
    if key == "overview":
        return _overview(as_of)
    spec = SPECS.get(key)
    if spec is None:
        names = ", ".join(f"china_{k}" for k in ["overview", *SPECS])
        return f"AKShare: '{indicator}' is not a known China macro series. Use one of: {names}."
    return _report(key, spec, as_of, look_back_days or DEFAULT_LOOKBACK_DAYS)
