"""Download the latest closed trading day's data by hand: ``python -m web.server.daily``.

It brings the daily snapshots up to the last closed trading day (Beijing time: a trading day
counts once it is past 15:30) and fetches once what the 行情 stats read, so the page opens
without waiting:

  * when the web server is up (``--server``, default http://127.0.0.1:8765), through it: the
    server's own sync (so it cannot run twice, and the server forgets its stale tables), then
    each stats endpoint once, which also fills the server's memory;
  * otherwise in this process, with the same functions the endpoints call.

What cannot be had yet (the 龙虎榜 before about 18:00, a feed that is down) is reported; run it
again later for those. Each run also re-checks some of the concept boards' stocks kept on disk
that are a month old, and logs what was added or removed (``concepts.refresh_due``). The log, in Beijing time, is also kept in ``.akshare_data/web/daily.log``.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from logging.handlers import RotatingFileHandler

log = logging.getLogger("tradingagents.daily")
SERVER = "http://127.0.0.1:8765"
SYNC_TIMEOUT = 45 * 60          # seconds to wait for the snapshot sync


def _setup_logging() -> None:
    from tradingagents.dataflows.vendors.akshare import store

    path = store.root() / "web" / "daily.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s CST %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fmt.converter = lambda t: time.gmtime(t + 8 * 3600)      # Beijing time, whatever the Mac's zone
    handlers: list[logging.Handler] = [RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")]
    handlers.append(logging.StreamHandler(sys.stdout))
    for h in handlers:
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def _get(url: str, method: str = "GET", timeout: float = 300) -> tuple[int, dict | None]:
    req = urllib.request.Request(url, method=method)
    # Straight to the local server, never through the system proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None


def server_up(server: str) -> bool:
    try:
        return _get(f"{server}/api/market/calendar", timeout=10)[0] == 200
    except OSError:
        return False


def _endpoints(day: str) -> list[str]:
    """What the 行情 page asks for on ``day``, the slow-to-fetch first."""
    return [
        f"market?date={day}", f"market/limits?date={day}", f"market/themes?days=5&date={day}",
        f"market/flow/industry?span=1d&date={day}", f"market/flow/industry?span=5d&date={day}",
        f"market/flow/industry?span=10d&date={day}",
        f"market/stats?range=60d&end={day}", f"market/breadth?range=60d&end={day}",
        f"market/sectors?days=20&end={day}", f"market/crowding?end={day}", f"market/valuation?end={day}",
        f"market/margin?range=60d&end={day}", f"market/qvix?range=60d&end={day}", f"market/flow?range=60d&end={day}",
        f"market/releases?date={day}", f"market/lhb?date={day}",
    ]


def via_server(server: str, day: str) -> tuple[int, int]:
    """(endpoints that failed, endpoints with nothing yet), after syncing the snapshots."""
    status, cal = _get(f"{server}/api/market/calendar")
    missing = (cal or {}).get("missing") or []
    if missing:
        log.info("同步快照：%s", "、".join(missing))
        status, s = _get(f"{server}/api/market/sync", "POST")
        deadline = time.time() + SYNC_TIMEOUT
        while (s or {}).get("state") == "running" and time.time() < deadline:
            time.sleep(10)
            _, s = _get(f"{server}/api/market/sync")
        log.info("快照同步：%s %s", (s or {}).get("state"), (s or {}).get("msg") or "")
        if (s or {}).get("state") != "ok":
            return 1, 0
    else:
        log.info("快照已是最新（%s）", day)
    failed = pending = 0
    for path in _endpoints(day):
        t = time.time()
        try:
            status, body = _get(f"{server}/api/{path}")
        except OSError as e:
            status, body = 0, {"detail": f"{type(e).__name__}: {e}"}
        info = body if isinstance(body, dict) else {}
        note = info.get("note")
        if status != 200:
            failed += 1
            log.warning("  %s → %s %s", path, status, note or info.get("detail") or "")
        elif info.get("available") is False:
            pending += 1
            log.warning("  %s → 暂不可得 · %s", path, note or "")
        else:
            log.info("  %s → ok (%.1fs)%s", path, time.time() - t, f" · {note}" if note else "")
    return failed, pending


def in_process(day: str) -> tuple[int, int]:
    """As ``via_server``, in this process."""
    from web.server import breadth, extras, limit_detail, market, sectors
    from web.server.sync_job import default_runner

    if market.missing_days():
        log.info("同步快照：%s", "、".join(market.missing_days()))
        res = default_runner()
        log.info("快照同步：%s %s", res.get("status"), res.get("msg") or "")
        market.invalidate()
        if market.missing_days():
            return 1, 0
    else:
        log.info("快照已是最新（%s）", day)
    steps: list[tuple[str, Callable[[], object]]] = [
        ("涨停详情", lambda: limit_detail.details(day)), ("跌停详情", lambda: limit_detail.details(day, side="down")),
        ("行情表", lambda: market.market_table(day)), ("涨停板", lambda: market.limit_board(day)),
        ("主线题材", lambda: extras.themes(day, 5)),
        *[(f"行业资金流 {s}", lambda s=s: extras.industry_flow(day, s)) for s in extras.FLOW_SPANS],
        ("市场统计", lambda: market.market_stats(day, "60d")), ("宽度与情绪", lambda: breadth.breadth(day, "60d")),
        ("行业热力图", lambda: sectors.sectors(day, 20)), ("行业拥挤度", lambda: sectors.crowding(day)),
        ("估值", lambda: sectors.valuation(day)), ("两融", lambda: extras.margin(day, "60d")),
        ("QVIX", lambda: extras.qvix(day, "60d")), ("市场资金流", lambda: extras.market_flow(day, "60d")),
        ("限售解禁", lambda: extras.releases(day)), ("龙虎榜", lambda: extras.lhb(day)),
    ]
    failed = pending = 0
    for name, fn in steps:
        t = time.time()
        try:
            r = fn()
            note = r.get("note") if isinstance(r, dict) else None
            if isinstance(r, dict) and r.get("available") is False:
                pending += 1
                log.warning("  %s → 暂不可得 · %s", name, note)
            else:
                log.info("  %s → ok (%.1fs)%s", name, time.time() - t, f" · {note}" if note else "")
        except Exception as e:  # noqa: BLE001 — one source down does not stop the rest
            failed += 1
            log.warning("  %s → 失败 %s: %s", name, type(e).__name__, e)
    return failed, pending


def _check_concepts() -> None:
    """The monthly check of the concept boards' stocks kept on disk (a few a run)."""
    from web.server import concepts

    try:
        r = concepts.refresh_due()
    except Exception as e:  # noqa: BLE001 — never fails the download
        log.warning("概念成分股检查失败：%s", e)
        return
    if not r["due"]:
        log.info("概念成分股：本地缓存都在 %d 天内检查过", concepts.CHECK_DAYS)
        return
    log.info("概念成分股：%d 个到期，本次检查 %d 个%s", r["due"], r["checked"],
             f"（东方财富暂不可用，余下的下次再查：{r['stopped']}）" if r["stopped"] else "")
    for c in r["changed"]:
        log.info("  %s：新增 %s；剔除 %s", c["name"], "、".join(x["name"] for x in c["added"]) or "无",
                 "、".join(x["name"] for x in c["removed"]) or "无")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="下载最近一个已收盘交易日的行情与统计数据")
    p.add_argument("--server", default=SERVER, help=f"web 服务地址（默认 {SERVER}；不可用时在本进程内下载）")
    args = p.parse_args(argv)
    from web.server import market

    _setup_logging()
    day = market.last_closed_day()
    up = server_up(args.server)
    log.info("开始下载 %s 的数据（%s）", day, "经由 web 服务" if up else "web 服务未运行，本进程下载")
    t = time.time()
    failed, pending = via_server(args.server, day) if up else in_process(day)
    _check_concepts()
    left = f"（{failed} 项失败、{pending} 项暂不可得，可稍后再运行一次）" if failed or pending else ""
    log.info("%s %s，用时 %.0fs%s", "部分完成" if left else "完成", day, time.time() - t, left)
    return 1 if left else 0


if __name__ == "__main__":
    raise SystemExit(main())
