"""Bring the market snapshots up to the latest closed trading day, in the background.

The market page can show any trading day up to the last one that has closed. A day after
the newest ``snapshots/YYYYMMDD`` directory is not on disk yet; picking it starts one job
that fetches today's whole-market quote and, for the trading days skipped in between,
each stock's daily bars (``snapshots.update``: the same as ``tradingagents-ashare sync
--only snapshots``). The page polls the job and reloads when it is done.

One job at a time; its last lines of progress are kept for the page to show.
"""
from __future__ import annotations

import contextlib
import logging
import threading
from collections import deque
from collections.abc import Callable
from datetime import datetime

log = logging.getLogger(__name__)

AKSHARE_LOGGER = "tradingagents.dataflows.vendors.akshare"


def default_runner() -> dict:
    """Fetch the whole-market quote and write the missing daily snapshots; the result of
    ``snapshots.update`` ({"status": "ok" | "skip" | "stale" | "incomplete", "msg", ...})."""
    from tradingagents.dataflows.vendors.akshare import spot, store, sync

    store.FALLBACKS.clear()
    df = spot.fetch_spot()
    res = sync._update_snapshots(df, refresh=False, allow_intraday=False, workers=4)
    return res or {"status": "error", "msg": "个股快照写入失败，详见后端日志"}


class _Lines(logging.Handler):
    def __init__(self, sink: deque):
        super().__init__(logging.INFO)
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        with contextlib.suppress(Exception):      # a progress line is never worth failing the job
            self.sink.append(record.getMessage().strip())


class SyncJob:
    def __init__(self, runner: Callable[[], dict] = default_runner,
                 on_done: Callable[[], None] | None = None):
        self.runner = runner
        self.on_done = on_done
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.state = "idle"              # idle | running | ok | error
        self.days: list[str] = []
        self.msg = ""
        self.lines: deque[str] = deque(maxlen=20)
        self.started: str | None = None
        self.finished: str | None = None

    def status(self) -> dict:
        return {"state": self.state, "days": self.days, "msg": self.msg, "lines": list(self.lines),
                "started": self.started, "finished": self.finished}

    def start(self, days: list[str]) -> dict:
        """Start a job for ``days`` (the trading days it should add); a job already running
        is left alone and its status returned."""
        with self._lock:
            if self.state == "running":
                return self.status()
            self.state, self.days, self.msg = "running", list(days), ""
            self.lines.clear()
            self.started, self.finished = datetime.now().isoformat(timespec="seconds"), None
            self._thread = threading.Thread(target=self._run, name="market-sync", daemon=True)
            self._thread.start()
            return self.status()

    def _run(self) -> None:
        logger = logging.getLogger(AKSHARE_LOGGER)
        handler, level = _Lines(self.lines), logger.level
        logger.addHandler(handler)
        if logger.getEffectiveLevel() > logging.INFO:
            logger.setLevel(logging.INFO)
        try:
            res = self.runner()
            ok = res.get("status") == "ok"
            state, msg = ("ok" if ok else "error"), str(res.get("msg") or "")
            if ok:
                msg = f"已同步到 {res.get('date', '')}" + (f"，补了 {res['gap_days']} 个漏掉的交易日" if res.get("gap_days") else "")
        except Exception as e:  # noqa: BLE001 - shown on the page
            log.exception("market sync failed")
            state, msg = "error", f"{type(e).__name__}: {e}"
        finally:
            logger.removeHandler(handler)
            logger.setLevel(level)
        if self.on_done:
            try:
                self.on_done()
            except Exception:  # noqa: BLE001
                log.exception("clearing the market caches failed")
        with self._lock:
            self.state, self.msg = state, msg
            self.finished = datetime.now().isoformat(timespec="seconds")

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)
