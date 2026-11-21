"""本地数据存储: akshare 入口、交易日历、分层缓存、增量时间序列、代码工具。

缓存策略 (policy):
  "daily"            按"最近一个已收盘交易日"缓存; 周末/节假日运行不会重复下载
  "weekly"           按自然周缓存 (成分股、增减持等低频数据)
  ("period", key, live)
                     按报告期缓存, 同一报告期只下载一次; live=True (披露季) 时每 7 天补一次
增量序列 (incremental):
  本地 parquet 只从最后日期往前回溯 overlap 天开始补数据, 合并去重
盘中保护:
  交易日 15:30 (北京时间) 之前运行时, 当天数据不写入缓存, 避免把盘中数据当收盘数据
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from tradingagents.dataflows.errors import (
    VendorError,
    VendorNotConfiguredError,
    VendorUnavailableError,
)
from tradingagents.dataflows.symbols import exchange_prefix
from tradingagents.dataflows.vendors.akshare import settings

log = logging.getLogger(__name__)

CST = ZoneInfo("Asia/Shanghai")
CLOSE_TIME = dt.time(15, 30)

# 本次运行中"拉取失败、退回旧数据"的数据源: {名称: 说明}。上层可据此提示数据可能过期。
FALLBACKS: dict[str, str] = {}


# ---------------------------------------------------------------------------
# akshare 入口
# ---------------------------------------------------------------------------
_TIMEOUT_INSTALLED = False


def install_http_timeout() -> None:
    """给 requests 注入默认超时: 防止某个网络请求挂死时整个进程无限期卡住。

    akshare 内部大量使用 requests 且多数未显式传 timeout (requests 默认 None = 无限等待),
    这里替换 HTTPAdapter.send, 仅对未指定 timeout 的请求补上 settings.HTTP_TIMEOUT。
    只在第一次真正使用 akshare 时安装 (幂等), 不影响只导入本包、不下载数据的进程。"""
    global _TIMEOUT_INSTALLED
    if _TIMEOUT_INSTALLED:
        return
    from requests.adapters import HTTPAdapter

    orig_send = HTTPAdapter.send

    def _send(self, request, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = settings.HTTP_TIMEOUT
        return orig_send(self, request, **kwargs)

    HTTPAdapter.send = _send
    _TIMEOUT_INSTALLED = True


def ak():
    """返回 akshare 模块 (安装了默认 HTTP 超时)。未安装时给出明确的安装提示。"""
    try:
        import akshare
    except ImportError as e:
        raise VendorNotConfiguredError(
            'A 股数据需要 akshare: pip install "tradingagents[ashare]"'
        ) from e
    install_http_timeout()
    return akshare


# ---------------------------------------------------------------------------
# 路径与通用工具
# ---------------------------------------------------------------------------
def root() -> Path:
    p = settings.data_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p


def snapshot_dir() -> Path:
    p = root() / "snapshots"
    p.mkdir(exist_ok=True)
    return p


def to_local_dates(s: pd.Series) -> pd.Series:
    """把混合格式的日期 (带时区的 '2026-11-06T08:00:00+08:00' / 不带时区的 '2026-11-06' / datetime) 统一为
    北京时间的日期 (tz-naive, 00:00)。带时区的值先换算到北京时间再取日期, 不会因 UTC 换算错到前一天。"""
    d = pd.to_datetime(s, errors="coerce", utc=True, format="mixed")
    return d.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None).dt.normalize()


def to_symbol(code: str) -> str | None:
    """'600519' -> 'SH600519' (快照文件名所用的格式); 无法识别交易所时返回 None。"""
    ex = exchange_prefix(code)
    return f"{ex}{str(code).strip().zfill(6)[-6:]}" if ex else None


# ---------------------------------------------------------------------------
# 交易日历
# ---------------------------------------------------------------------------
_CAL: pd.DatetimeIndex | None = None


def trade_calendar() -> pd.DatetimeIndex:
    """新浪交易日历, 按月缓存; 失败时退回工作日近似。"""
    global _CAL
    if _CAL is not None:
        return _CAL
    path = root() / f"_calendar_{dt.date.today():%Y%m}.pkl"
    try:
        if path.exists():
            cal = pd.read_pickle(path)
        else:
            cal = pd.DatetimeIndex(pd.to_datetime(ak().tool_trade_date_hist_sina()["trade_date"]))
            cal.to_series().to_pickle(path)
            for old in root().glob("_calendar_*.pkl"):
                if old != path:
                    old.unlink(missing_ok=True)
        _CAL = pd.DatetimeIndex(cal)
    except Exception as e:
        log.warning("交易日历获取失败, 用工作日近似: %s", e)
        _CAL = pd.bdate_range("2000-01-01", f"{dt.date.today().year + 1}-12-31")
    return _CAL


def reset_calendar() -> None:
    """清掉进程内的交易日历 (切换数据目录或测试时使用)。"""
    global _CAL
    _CAL = None


def now_cst() -> dt.datetime:
    return dt.datetime.now(CST)


def is_intraday(now: dt.datetime | None = None) -> bool:
    """今天是交易日且未到 15:30 (北京时间)。"""
    now = now or now_cst()
    today = pd.Timestamp(now.date())
    return today in trade_calendar() and now.time() < CLOSE_TIME


def market_session(now: dt.datetime | None = None) -> str:
    """当前 A 股交易时段 (北京时间): 非交易日 / 盘前 / 交易中 / 午休 / 收盘中 (15:00–15:30, 等待收盘数据) / 收盘后。"""
    now = now or now_cst()
    if pd.Timestamp(now.date()) not in trade_calendar():
        return "非交易日"
    t = now.time()
    if t < dt.time(9, 30):
        return "盘前"
    if t < dt.time(11, 30):
        return "交易中"
    if t < dt.time(13, 0):
        return "午休"
    if t < dt.time(15, 0):
        return "交易中"
    if t < CLOSE_TIME:
        return "收盘中"
    return "收盘后"


def last_closed_trade_date(now: dt.datetime | None = None) -> dt.date:
    """最近一个已收盘的交易日。"""
    now = now or now_cst()
    cal = trade_calendar()
    today = pd.Timestamp(now.date())
    cands = cal[cal < today] if is_intraday(now) else cal[cal <= today]
    return cands[-1].date() if len(cands) else (now.date() - dt.timedelta(days=1))


# ---------------------------------------------------------------------------
# 分层缓存
# ---------------------------------------------------------------------------
def _key(policy) -> tuple[str, bool]:
    """返回 (缓存键, 是否需要按时间强制刷新)。"""
    d = last_closed_trade_date()
    if policy == "daily":
        return d.strftime("%Y%m%d"), False
    if policy == "weekly":
        y, w, _ = d.isocalendar()
        return f"{y}W{w:02d}", False
    if policy == "monthly":
        return f"{d.year}M{d.month:02d}", False
    if isinstance(policy, tuple) and policy[0] == "period":
        return f"P{policy[1]}", bool(policy[2])
    raise ValueError(f"未知缓存策略 {policy}")


def cached(name: str, fn: Callable[[], pd.DataFrame], policy="daily", refresh: bool = False,
           retries: int = 3) -> pd.DataFrame:
    """整表下载 + 按 policy 缓存到 <name>__<键>.pkl; 新键写入后删除旧键。下载失败时退回最近的旧缓存。"""
    key, live = _key(policy)
    path = root() / f"{name}__{key}.pkl"
    if path.exists() and not refresh:
        age_days = (time.time() - path.stat().st_mtime) / 86400
        if not (live and age_days > 7):
            log.info("    · %s 命中缓存 %s", name, path.name)
            return pd.read_pickle(path)
    err = None
    for i in range(retries):
        try:
            df = fn()
            if df is None or len(df) == 0:
                raise ValueError("空结果")
            # 盘中拿到的 'daily' 数据不落盘 (收盘后再运行会重新拉取)
            if not (policy == "daily" and is_intraday()):
                df.to_pickle(path)
                for old in root().glob(f"{name}__*.pkl"):
                    if old != path:
                        old.unlink(missing_ok=True)
            return df
        except Exception as e:
            err = e
            time.sleep(1.5 * (i + 1))
    olds = sorted(root().glob(f"{name}__*.pkl"), key=lambda p: p.stat().st_mtime)
    if olds:
        log.warning("    ! %s 拉取失败, 使用旧缓存 %s", name, olds[-1].name)
        FALLBACKS[name] = (f"拉取失败, 使用旧缓存 {olds[-1].name.split('__')[-1].removesuffix('.pkl')}: "
                           f"{type(err).__name__}")
        return pd.read_pickle(olds[-1])
    raise RuntimeError(f"{type(err).__name__}: {err}")


# ---------------------------------------------------------------------------
# 单只股票的数据 (供分析智能体按需读取)
# ---------------------------------------------------------------------------
# 盘中请求当天的数据时, 缓存超过这个秒数就重新拉取 (盘中行情一直在变)
QUOTE_TTL_SECONDS = 900


def symbol_cache(kind: str, symbol: str, fetch: Callable[[], pd.DataFrame], live: bool = False) -> pd.DataFrame:
    """单只股票的下载结果缓存在 agent/<kind>/<symbol>.pkl, 当天 (北京时间) 有效。

    live: 请求覆盖到今天; 盘中时缓存超过 QUOTE_TTL_SECONDS 就重新拉取。"""
    path = root() / "agent" / kind / f"{symbol}.pkl"
    # 一次分析里几位分析师并行读同一只股票: 同一文件同一时刻只让一个线程下载, 其余等它写完直接读缓存
    with _path_lock(path):
        now = now_cst()
        if path.exists():
            written = dt.datetime.fromtimestamp(path.stat().st_mtime, CST)
            expired = live and is_intraday(now) and (now - written).total_seconds() > QUOTE_TTL_SECONDS
            if written.date() == now.date() and not expired:
                return pd.read_pickle(path)
        df = fetch()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = _tmp_of(path)
        df.to_pickle(tmp)
        os.replace(tmp, path)
        return df


_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.Lock:
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(str(path), threading.Lock())


def _tmp_of(path: Path) -> Path:
    """写入用的临时文件: 每个进程 / 线程各用各的名字, 并发写同一文件时不会互相把对方的临时文件改名走。"""
    return path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")


def call(fn: Callable, what: str):
    """调用 akshare; 网络 / 接口异常记为 VendorUnavailableError (说明的是数据源, 不是这只股票)。
    分页接口的 tqdm 进度条会搅乱 CLI 的实时界面, 调用期间关闭。"""
    previous = os.environ.get("TQDM_DISABLE")
    os.environ["TQDM_DISABLE"] = "1"
    try:
        return fn()
    except VendorError:
        raise
    except Exception as e:
        raise VendorUnavailableError(f"AKShare {what} failed: {type(e).__name__}: {str(e)[:200]}") from e
    finally:
        if previous is None:
            os.environ.pop("TQDM_DISABLE", None)
        else:
            os.environ["TQDM_DISABLE"] = previous


# ---------------------------------------------------------------------------
# 增量时间序列
# ---------------------------------------------------------------------------
def ts_path(name: str) -> Path:
    return root() / "ts" / f"{name}.parquet"


def incremental(name: str, fetch: Callable[[str], pd.DataFrame], date_col: str, full_start: str,
                refresh: bool = False, overlap_days: int = 10, key_cols: tuple = ()) -> pd.DataFrame:
    """fetch(start_yyyymmdd) -> DataFrame。优先读本地 ts/<name>.parquet, 只下载缺失的最近日期,
    按 (date_col, *key_cols) 去重。"""
    path = ts_path(name)
    path.parent.mkdir(exist_ok=True)
    old = pd.read_parquet(path) if path.exists() and not refresh else None
    if old is not None and len(old):
        last = to_local_dates(old[date_col]).max()
        if last.date() >= last_closed_trade_date():
            log.info("    · %s 本地 parquet 已是最新, 跳过下载", name)
            return old
        start = (last - pd.Timedelta(days=overlap_days)).strftime("%Y%m%d")
    else:
        start = full_start
    try:
        new = fetch(start)
    except Exception as e:
        if old is not None:
            log.warning("    ! %s 增量更新失败, 使用本地数据: %s", name, e)
            FALLBACKS[name] = (f"增量更新失败, 使用本地数据 (截至 {to_local_dates(old[date_col]).max():%Y-%m-%d}): "
                               f"{type(e).__name__}")
            return old
        raise
    df = new if old is None else pd.concat([old, new], ignore_index=True)
    df["_d"] = to_local_dates(df[date_col])        # 新旧数据的日期格式可能不同 (带 / 不带时区)
    df = df.dropna(subset=["_d"]).drop_duplicates(["_d", *key_cols], keep="last").sort_values(["_d", *key_cols])
    live_view = df.drop(columns="_d")
    # 盘中: 当天的数据只返回、不落盘
    if is_intraday():
        df = df[df["_d"].dt.date < now_cst().date()]
    _write_ts(df.drop(columns="_d"), path)
    return live_view


def _write_ts(out: pd.DataFrame, path: Path) -> None:
    out = out.copy()
    for c in out.columns:                       # parquet 需要统一类型
        if out[c].dtype == object:
            out[c] = out[c].astype(str)
    tmp = _tmp_of(path)
    out.to_parquet(tmp, index=False)
    os.replace(tmp, path)
