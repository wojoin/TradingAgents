"""A-share fundamentals for the analysts: valuation, financial statements, industry context.

Point in time, like the SEC EDGAR vendor:
  · valuation multiples come from Eastmoney's daily valuation history, read on the
    analysis date;
  · statements are the reports published (公告日期) on or before the analysis
    date. Their figures are as Eastmoney carries them today, which can include
    later restatements;
  · present-day facts (name, Shenwan industry membership) are served only to a
    run dated today, as ``date_window.withhold_live_profile`` requires.

A-share income and cash-flow reports are cumulative year to date: 一季报 = Q1,
中报 = H1, 三季报 = Q1–Q3, 年报 = the full year. They are shown as reported, never
differenced into single quarters.
"""
from __future__ import annotations

import logging

import pandas as pd

from tradingagents.dataflows.date_window import get_current_date, is_historical
from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError
from tradingagents.dataflows.symbols import normalize_symbol
from tradingagents.dataflows.vendors.akshare import store
from tradingagents.dataflows.vendors.akshare.prices import require_code

logger = logging.getLogger(__name__)

YI = 1e8                                  # 亿 = 100 million CNY

# (field, label, kind): kind "money" in 亿元, "pct" in %, "cny" in CNY per share
STATEMENTS = {
    "income": ("stock_profit_sheet_by_report_em", "Income Statement", True, [
        ("TOTAL_OPERATE_INCOME", "营业总收入 Total operating revenue", "money"),
        ("TOTAL_OPERATE_INCOME_YOY", "营业总收入同比 Revenue YoY", "pct"),
        ("OPERATE_INCOME", "营业收入 Operating revenue", "money"),
        ("OPERATE_COST", "营业成本 Operating cost", "money"),
        ("SALE_EXPENSE", "销售费用 Selling expense", "money"),
        ("MANAGE_EXPENSE", "管理费用 Administrative expense", "money"),
        ("RESEARCH_EXPENSE", "研发费用 R&D expense", "money"),
        ("FINANCE_EXPENSE", "财务费用 Finance expense", "money"),
        ("OPERATE_PROFIT", "营业利润 Operating profit", "money"),
        ("TOTAL_PROFIT", "利润总额 Profit before tax", "money"),
        ("INCOME_TAX", "所得税 Income tax", "money"),
        ("NETPROFIT", "净利润 Net profit", "money"),
        ("PARENT_NETPROFIT", "归母净利润 Net profit to shareholders", "money"),
        ("PARENT_NETPROFIT_YOY", "归母净利润同比 Net profit YoY", "pct"),
        ("DEDUCT_PARENT_NETPROFIT", "扣非归母净利润 Recurring net profit", "money"),
        ("DEDUCT_PARENT_NETPROFIT_YOY", "扣非归母净利润同比 Recurring net profit YoY", "pct"),
        ("BASIC_EPS", "基本每股收益 Basic EPS", "cny"),
        ("DILUTED_EPS", "稀释每股收益 Diluted EPS", "cny"),
    ]),
    "balance": ("stock_balance_sheet_by_report_em", "Balance Sheet", False, [
        ("TOTAL_ASSETS", "资产总计 Total assets", "money"),
        ("TOTAL_CURRENT_ASSETS", "流动资产合计 Current assets", "money"),
        ("MONETARYFUNDS", "货币资金 Cash and equivalents", "money"),
        ("ACCOUNTS_RECE", "应收账款 Accounts receivable", "money"),
        ("INVENTORY", "存货 Inventory", "money"),
        ("FIXED_ASSET", "固定资产 Fixed assets", "money"),
        ("GOODWILL", "商誉 Goodwill", "money"),
        ("TOTAL_LIABILITIES", "负债合计 Total liabilities", "money"),
        ("TOTAL_CURRENT_LIAB", "流动负债合计 Current liabilities", "money"),
        ("SHORT_LOAN", "短期借款 Short-term borrowings", "money"),
        ("LONG_LOAN", "长期借款 Long-term borrowings", "money"),
        ("CONTRACT_LIAB", "合同负债 Contract liabilities", "money"),
        ("TOTAL_EQUITY", "所有者权益合计 Total equity", "money"),
        ("TOTAL_PARENT_EQUITY", "归母所有者权益 Equity to shareholders", "money"),
    ]),
    "cashflow": ("stock_cash_flow_sheet_by_report_em", "Cash Flow Statement", True, [
        ("NETCASH_OPERATE", "经营活动现金流量净额 Operating cash flow", "money"),
        ("NETCASH_INVEST", "投资活动现金流量净额 Investing cash flow", "money"),
        ("NETCASH_FINANCE", "筹资活动现金流量净额 Financing cash flow", "money"),
        ("CONSTRUCT_LONG_ASSET", "购建长期资产支付的现金 Capital expenditure", "money"),
        ("CCE_ADD", "现金及等价物净增加额 Net change in cash", "money"),
        ("END_CCE", "期末现金及等价物 Cash at end of period", "money"),
    ]),
}
PERIODS = {"quarterly": 8, "annual": 5}

# (column of stock_value_em, label, divisor, unit)
VALUATION = [
    ("当日收盘价", "Close (unadjusted)", 1, " CNY"),
    ("总市值", "Market cap", YI, " 亿元"),
    ("流通市值", "Float market cap", YI, " 亿元"),
    ("PE(TTM)", "PE (TTM)", 1, ""),
    ("PE(静)", "PE (static, last annual report)", 1, ""),
    ("市净率", "Price to book", 1, ""),
    ("PEG值", "PEG", 1, ""),
    ("市现率", "Price to operating cash flow", 1, ""),
    ("市销率", "Price to sales", 1, ""),
]


def num(value, scale: float = 1) -> float:
    v = pd.to_numeric(value, errors="coerce")
    return v / scale if pd.notna(v) else float("nan")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def _reports(kind: str, code: str, as_of_date: str | None) -> pd.DataFrame:
    """One statement's reports published on or before ``as_of_date``, newest first."""
    api = STATEMENTS[kind][0]
    sym = store.to_symbol(code)
    df = store.symbol_cache(f"report_{kind}", sym,
                            lambda: store.call(lambda: getattr(store.ak(), api)(symbol=sym), STATEMENTS[kind][1]))
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"], errors="coerce")
    df["NOTICE_DATE"] = pd.to_datetime(df["NOTICE_DATE"], errors="coerce")
    cutoff = pd.Timestamp(as_of_date or get_current_date())
    df = df[df["NOTICE_DATE"].notna() & (df["NOTICE_DATE"] <= cutoff)]
    return df.sort_values("REPORT_DATE", ascending=False).reset_index(drop=True)


def _valuation(code: str, as_of_date: str) -> pd.Series | None:
    """Eastmoney's daily valuation row on or before ``as_of_date``."""
    df = store.symbol_cache("valuation", store.to_symbol(code),
                            lambda: store.call(lambda: store.ak().stock_value_em(symbol=code), "valuation history"),
                            live=not is_historical(as_of_date))
    if df is None or df.empty:
        return None
    d = pd.to_datetime(df["数据日期"], errors="coerce")
    rows = df[d <= pd.Timestamp(as_of_date)]
    return rows.iloc[-1] if len(rows) else None


def _local_valuation(code: str, as_of_date: str) -> pd.Series | None:
    """The local snapshot's last row with PE/PB on or before ``as_of_date`` (offline fallback)."""
    from tradingagents.dataflows.vendors.akshare import snapshots
    try:
        df = snapshots.load_stock(store.to_symbol(code), asof=as_of_date)
    except FileNotFoundError:
        return None
    df = df.dropna(subset=["pe_dynamic", "pb"], how="all")
    return df.iloc[-1] if len(df) else None


def _latest_local(pattern: str) -> pd.DataFrame | None:
    files = sorted(store.settings.data_dir().glob(pattern))
    return pd.read_pickle(files[-1]) if files else None


def local_profile(code: str) -> dict:
    """Today's name and Shenwan industries from ``.akshare_data`` (no network)."""
    out: dict[str, str] = {}
    spot = _latest_local("spot__*.pkl")
    if spot is not None and "代码" in spot:
        hit = spot[spot["代码"].astype(str).str.zfill(6) == code]
        if len(hit):
            out["name"] = str(hit["名称"].iat[0])
    comp, first = _latest_local("sw_comp__*.pkl"), _latest_local("sw_first__*.pkl")
    if comp is not None and first is not None:
        hit = comp[comp["证券代码"].astype(str).str.zfill(6) == code]
        if len(hit):
            ind = str(hit["行业代码"].iat[0])
            out["sw1_code"] = ind
            names = first.assign(c=first["行业代码"].astype(str).str.extract(r"(\d{6})")[0])
            match = names[names["c"] == ind]
            if len(match):
                out["sw1"] = str(match["行业名称"].iat[0])
            if "name" not in out:
                out["name"] = str(hit["证券名称"].iat[0])
    cons, second = _latest_local("sw_second_cons__*.pkl"), _latest_local("sw_second__*.pkl")
    if cons is not None and second is not None:
        hit = cons[cons["证券代码"].astype(str).str.zfill(6) == code]
        if len(hit):
            c2 = str(hit["二级代码"].iat[0])
            names = second.assign(c=second["行业代码"].astype(str).str.extract(r"(\d{6})")[0])
            match = names[names["c"] == c2]
            if len(match):
                out["sw2"] = str(match["行业名称"].iat[0])
    return out


def _industry_context(sw1_code: str, as_of_date: str) -> list[str]:
    """The Shenwan level-1 industry's valuation on the date, with its 5-year percentile."""
    path = store.ts_path("sw_daily")
    if not path.exists():
        return []
    df = pd.read_parquet(path)
    df = df[df["指数代码"].astype(str).str.contains(sw1_code)].copy()
    df["d"] = pd.to_datetime(df["发布日期"], errors="coerce")
    df = df[df["d"] <= pd.Timestamp(as_of_date)].sort_values("d")
    if df.empty:
        return []
    last = df.iloc[-1]
    window = df[df["d"] > last["d"] - pd.DateOffset(years=5)]
    lines = [f"Industry data date: {last['d']:%Y-%m-%d}"]
    for col, label in (("市盈率", "Industry PE"), ("市净率", "Industry PB"), ("股息率", "Industry dividend yield %")):
        value = pd.to_numeric(window[col], errors="coerce")
        if pd.notna(value.iloc[-1]):
            pct = (value <= value.iloc[-1]).mean() * 100
            lines.append(f"{label}: {value.iloc[-1]:.2f} ({pct:.0f}th percentile of the last 5 years)")
    return lines


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def _fmt(value, kind: str) -> str:
    v = pd.to_numeric(value, errors="coerce")
    if pd.isna(v):
        return ""
    if kind == "money":
        return f"{v / YI:.2f}"
    if kind == "pct":
        return f"{v:.2f}%"
    return f"{v:.3f}"


def _ratio(num, den) -> float | None:
    num, den = pd.to_numeric(num, errors="coerce"), pd.to_numeric(den, errors="coerce")
    return None if pd.isna(num) or pd.isna(den) or den == 0 else num / den


# ---------------------------------------------------------------------------
# Vendor methods
# ---------------------------------------------------------------------------
def _statement(kind: str, ticker: str, freq: str, as_of_date: str | None) -> str:
    code = require_code(ticker)
    canonical = normalize_symbol(ticker)
    _, title, cumulative, fields = STATEMENTS[kind]
    freq = freq.lower()
    if freq not in PERIODS:
        raise ValueError(f"freq must be 'annual' or 'quarterly', got {freq!r}")
    df = _reports(kind, code, as_of_date)
    if freq == "annual":
        df = df[df["REPORT_TYPE"] == "年报"]
    df = df.head(PERIODS[freq])
    cutoff = as_of_date or get_current_date()
    if df.empty:
        raise NoMarketDataError(ticker, canonical, f"no {freq} {title.lower()} published by {cutoff}")
    rows = [["公告日期 Published"] + [f"{d:%Y-%m-%d}" for d in df["NOTICE_DATE"]]]
    for field, label, fmt in fields:
        if field in df.columns and df[field].notna().any():
            rows.append([label] + [_fmt(v, fmt) for v in df[field]])
    table = pd.DataFrame(rows, columns=["Item", *df["REPORT_DATE_NAME"].astype(str)])
    header = (
        f"# {title} for {canonical} ({freq}), CNY 100 million (亿元) unless the row says otherwise\n"
        f"# Reports published (公告日期) on or before {cutoff}; figures as currently carried "
        f"by Eastmoney, which can include later restatements\n"
    )
    if cumulative:
        header += ("# A-share reports are cumulative year to date: 一季报 = Q1, 中报 = H1, "
                   "三季报 = Q1-Q3, 年报 = full year\n")
    return header + "\n" + table.to_csv(index=False)


def get_balance_sheet(ticker: str, freq: str = "quarterly", as_of_date: str | None = None) -> str:
    """Balance sheets published on or before ``as_of_date``."""
    return _statement("balance", ticker, freq, as_of_date)


def get_income_statement(ticker: str, freq: str = "quarterly", as_of_date: str | None = None) -> str:
    """Income statements published on or before ``as_of_date`` (cumulative year to date)."""
    return _statement("income", ticker, freq, as_of_date)


def get_cashflow(ticker: str, freq: str = "quarterly", as_of_date: str | None = None) -> str:
    """Cash flow statements published on or before ``as_of_date`` (cumulative year to date)."""
    return _statement("cashflow", ticker, freq, as_of_date)


def get_fundamentals(ticker: str, as_of_date: str | None = None) -> str:
    """Valuation on the date, the latest published report's key figures, and (for a run
    dated today) the company's name and Shenwan industry context."""
    code = require_code(ticker)
    canonical = normalize_symbol(ticker)
    as_of_date = as_of_date or get_current_date()
    historical = is_historical(as_of_date)
    sections: list[tuple[str, list[str]]] = []

    if not historical:
        prof = local_profile(code)
        lines = [f"Name: {prof['name']}"] if "name" in prof else []
        if "sw1" in prof:
            lines.append(f"Shenwan industry (申万一级): {prof['sw1']}")
        if "sw2" in prof:
            lines.append(f"Shenwan sub-industry (申万二级): {prof['sw2']}")
        if lines:
            sections.append(("Company", lines))

    try:
        val = _valuation(code, as_of_date)
    except Exception as e:  # valuation is one section of several; fall back to the local snapshot
        logger.warning("A-share valuation history unavailable for %s: %s", code, e)
        val = None
    if val is not None:
        lines = [f"{label}: {num(val.get(col), scale):.2f}{unit}"
                 for col, label, scale, unit in VALUATION if pd.notna(num(val.get(col), scale))]
        sections.append((f"Valuation on {pd.Timestamp(val['数据日期']):%Y-%m-%d} (Eastmoney)", lines))
    elif (loc := _local_valuation(code, as_of_date)) is not None:
        lines = [f"Close: {loc['close']:.2f} CNY (unadjusted)"]
        if pd.notna(loc["pe_dynamic"]):
            lines.append(f"PE (dynamic): {loc['pe_dynamic']:.2f}")
        if pd.notna(loc["pb"]):
            lines.append(f"Price to book: {loc['pb']:.2f}")
        if pd.notna(loc["total_mv"]):
            lines.append(f"Market cap: {loc['total_mv'] / YI:.2f} 亿元")
        sections.append((f"Valuation on {loc['trade_date']:%Y-%m-%d} (local snapshot)", lines))

    unavailable = None
    try:
        income = _reports("income", code, as_of_date)
        balance = _reports("balance", code, as_of_date) if len(income) else None
    except VendorUnavailableError as e:      # serve the other sections; say this one is missing
        unavailable, income = e, pd.DataFrame()
    if len(income):
        r = income.iloc[0]
        b = balance[balance["REPORT_DATE"] == r["REPORT_DATE"]]
        b = b.iloc[0] if len(b) else None
        lines = [f"Report: {r['REPORT_DATE_NAME']} (period ending {r['REPORT_DATE']:%Y-%m-%d}, "
                 f"published {r['NOTICE_DATE']:%Y-%m-%d}); income figures are year to date"]
        for field, label, fmt in STATEMENTS["income"][3]:
            if field in ("TOTAL_OPERATE_INCOME", "TOTAL_OPERATE_INCOME_YOY", "PARENT_NETPROFIT",
                         "PARENT_NETPROFIT_YOY", "DEDUCT_PARENT_NETPROFIT_YOY", "BASIC_EPS") \
                    and pd.notna(r.get(field)):
                lines.append(f"{label}: {_fmt(r[field], fmt)}{' 亿元' if fmt == 'money' else ''}")
        revenue = r.get("OPERATE_INCOME")
        if (gm := _ratio(pd.to_numeric(revenue, errors="coerce") - pd.to_numeric(r.get("OPERATE_COST"), errors="coerce"),
                         revenue)) is not None:
            lines.append(f"Gross margin: {gm * 100:.2f}%")
        if (nm := _ratio(r.get("PARENT_NETPROFIT"), revenue)) is not None:
            lines.append(f"Net margin: {nm * 100:.2f}%")
        if b is not None:
            if (roe := _ratio(r.get("PARENT_NETPROFIT"), b.get("TOTAL_PARENT_EQUITY"))) is not None:
                lines.append(f"ROE (year to date, not annualized): {roe * 100:.2f}%")
            if (lev := _ratio(b.get("TOTAL_LIABILITIES"), b.get("TOTAL_ASSETS"))) is not None:
                lines.append(f"Liabilities to assets: {lev * 100:.2f}%")
        sections.append(("Latest published report", lines))

    if not historical and (sw1 := local_profile(code).get("sw1_code")):
        lines = _industry_context(sw1, as_of_date)
        if lines:
            sections.append(("Shenwan industry valuation (申万一级)", lines))

    if not sections:
        if unavailable is not None:
            raise unavailable
        raise NoMarketDataError(ticker, canonical, f"no fundamentals available by {as_of_date}")
    if unavailable is not None:
        sections.append(("Latest published report", [f"Unavailable right now ({unavailable}); "
                                                     "do not estimate these figures"]))
    out = [f"# Company Fundamentals for {canonical}", f"# Point-in-time as of: {as_of_date}"]
    if historical:
        out.append("# Name and industry membership are withheld: they reflect today, not this date")
    for title, lines in sections:
        out += ["", f"## {title}", *lines]
    return "\n".join(out)
