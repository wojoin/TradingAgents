"""Analysis runs started from the web: a queue, one run at a time, each an event log.

A run streams the trading graph the way the CLI does and turns each step into
events the page follows over SSE:

  status   the run's state: queued, running, completed, failed
  agent    an agent's state: pending, in_progress, completed
  section  a report section's latest text (analyst reports, debates, plans)
  tool     a tool an agent called
  done     the saved report's id and the rating
  error    why the run failed

Runs live in memory; a finished run's report is on disk under results_dir/reports,
where the reports list reads it. One run at a time: the graph makes many model
and data calls, and parallel runs would trip providers' and Eastmoney's limits.
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from tradingagents.dataflows.symbols import normalize_symbol

# The agents a run reports on, in order; analysts appear only when selected.
ANALYST_AGENTS = {
    "market": "Market Analyst",
    "social": "Sentiment Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
}
TEAM_AGENTS = ("Bull Researcher", "Bear Researcher", "Research Manager", "Trader",
               "Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager")
# Report sections streamed to the page: key -> (title, agent).
SECTIONS = {
    "market_report": ("市场/技术分析", "Market Analyst"),
    "sentiment_report": ("情绪分析", "Sentiment Analyst"),
    "news_report": ("新闻分析", "News Analyst"),
    "fundamentals_report": ("基本面分析", "Fundamentals Analyst"),
    "bull_history": ("多头研究员", "Bull Researcher"),
    "bear_history": ("空头研究员", "Bear Researcher"),
    "investment_plan": ("研究经理", "Research Manager"),
    "trader_investment_plan": ("交易员", "Trader"),
    "aggressive_history": ("激进风控", "Aggressive Analyst"),
    "conservative_history": ("保守风控", "Conservative Analyst"),
    "neutral_history": ("中性风控", "Neutral Analyst"),
    "final_trade_decision": ("投资组合经理决策", "Portfolio Manager"),
}


@dataclass
class Run:
    id: str
    ticker: str
    symbol: str
    trade_date: str
    status: str = "queued"
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    started: str | None = None
    finished: str | None = None
    report_id: str | None = None
    rating: str | None = None
    error: str | None = None
    agents: dict[str, str] = field(default_factory=dict)
    sections: dict[str, str] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    options: object | None = None    # web.server.settings.RunOptions

    def summary(self) -> dict:
        from dataclasses import asdict, is_dataclass

        out = {k: getattr(self, k) for k in ("id", "ticker", "symbol", "trade_date", "status", "created",
                                             "started", "finished", "report_id", "rating", "error")}
        out["options"] = asdict(self.options) if is_dataclass(self.options) else None
        return out

    def detail(self) -> dict:
        return {**self.summary(), "agents": dict(self.agents),
                "sections": {k: {"title": SECTIONS[k][0], "content": v} for k, v in self.sections.items()}}


class Progress:
    """Turns the graph's streamed state into agent and section events."""

    def __init__(self, run: Run, emit: Callable[[str, dict], None], analysts: list[str]):
        self.run, self.emit = run, emit
        names = [ANALYST_AGENTS[a] for a in analysts if a in ANALYST_AGENTS] + list(TEAM_AGENTS)
        run.agents = dict.fromkeys(names, "pending")
        for a in analysts:
            self.agent(ANALYST_AGENTS[a], "in_progress")

    def agent(self, name: str, status: str) -> None:
        if name in self.run.agents and self.run.agents[name] != status and \
                not (self.run.agents[name] == "completed" and status == "in_progress"):
            self.run.agents[name] = status
            self.emit("agent", {"agent": name, "status": status})

    def section(self, key: str, content) -> None:
        text = str(content or "").strip()
        if text and self.run.sections.get(key) != text:
            self.run.sections[key] = text
            self.emit("section", {"key": key, "title": SECTIONS[key][0], "content": text})

    def update(self, chunk: dict) -> None:
        for key in ("market_report", "sentiment_report", "news_report", "fundamentals_report"):
            if chunk.get(key):
                self.section(key, chunk[key])
                self.agent(SECTIONS[key][1], "completed")
        debate = chunk.get("investment_debate_state") or {}
        for key in ("bull_history", "bear_history"):
            if debate.get(key):
                self.agent(SECTIONS[key][1], "in_progress")
                self.section(key, debate[key])
        if chunk.get("investment_plan"):
            self.section("investment_plan", chunk["investment_plan"])
            for name in ("Bull Researcher", "Bear Researcher", "Research Manager"):
                self.agent(name, "completed")
            self.agent("Trader", "in_progress")
        if chunk.get("trader_investment_plan"):
            self.section("trader_investment_plan", chunk["trader_investment_plan"])
            self.agent("Trader", "completed")
        risk = chunk.get("risk_debate_state") or {}
        for key in ("aggressive_history", "conservative_history", "neutral_history"):
            if risk.get(key):
                self.agent(SECTIONS[key][1], "in_progress")
                self.section(key, risk[key])
        if chunk.get("final_trade_decision"):
            self.section("final_trade_decision", chunk["final_trade_decision"])
            for name in ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager"):
                self.agent(name, "completed")


# A runner does the work: (run, progress-emitting callback) -> (report directory, rating).
Runner = Callable[[Run, Callable[[str, dict], None]], tuple[Path, str]]


def graph_runner(run: Run, emit: Callable[[str, dict], None]) -> tuple[Path, str]:
    """Run the trading graph for ``run`` with its options and save its report."""
    from tradingagents.agents.rating import run_rating
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from web.server.settings import run_config, validate

    config, analysts = run_config(run.options or validate({}))
    progress = Progress(run, emit, analysts)
    graph = TradingAgentsGraph(analysts, config=config, debug=False)
    state = graph.create_run_state(run.symbol, run.trade_date)
    args = graph.propagator.get_graph_args()
    final_state: dict = {}
    for messages, chunk in graph.stream_run(state, **args):
        for message in messages:
            for call in getattr(message, "tool_calls", None) or []:
                name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "")
                if name:
                    emit("tool", {"name": name})
        if chunk:
            progress.update(chunk)
            final_state.update(chunk)
    graph.record_decision(run.symbol, run.trade_date, final_state)
    report = graph.save_reports(final_state, run.symbol)
    return report.parent, run_rating(final_state)


class RunManager:
    """Queues runs, executes them one at a time, and keeps each run's events."""

    def __init__(self, runner: Runner = graph_runner, today: Callable[[], str] | None = None):
        from tradingagents.dataflows.date_window import get_current_date

        self.runner = runner
        self.today = today or get_current_date
        self.runs: dict[str, Run] = {}
        self.lock = threading.Lock()
        self.changed = threading.Condition(self.lock)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")

    def submit(self, ticker: str, options=None) -> Run:
        """Queue a run of ``ticker``; ``options`` (RunOptions) sets its date, analysts, models ..."""
        raw = (ticker or "").strip()
        if not raw or len(raw) > 20 or not all(c.isalnum() or c in ".-^=" for c in raw):
            raise ValueError(f"not a ticker: {ticker!r}")
        date = getattr(options, "date", None) or self.today()
        run = Run(id=uuid.uuid4().hex[:12], ticker=raw, symbol=normalize_symbol(raw), trade_date=date,
                  options=options)
        with self.lock:
            self.runs[run.id] = run
            self._emit(run, "status", {"status": "queued"})
        self.pool.submit(self._execute, run)
        return run

    def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id)

    def list(self) -> list[Run]:
        return sorted(self.runs.values(), key=lambda r: r.created, reverse=True)

    def events_after(self, run: Run, seq: int, timeout: float) -> list[dict]:
        """Events with a sequence number above ``seq``, waiting up to ``timeout`` for one."""
        with self.changed:
            if len(run.events) <= seq and run.status in ("queued", "running"):
                self.changed.wait(timeout)
            return run.events[seq:]

    def _emit(self, run: Run, kind: str, data: dict) -> None:
        """Append an event; the caller may or may not hold the lock (it is re-entrant here)."""
        run.events.append({"seq": len(run.events) + 1, "type": kind, "data": data})
        self.changed.notify_all()

    def emitter(self, run: Run) -> Callable[[str, dict], None]:
        def emit(kind: str, data: dict) -> None:
            with self.lock:
                self._emit(run, kind, data)
        return emit

    def _execute(self, run: Run) -> None:
        emit = self.emitter(run)
        run.status, run.started = "running", datetime.now().isoformat(timespec="seconds")
        emit("status", {"status": "running"})
        try:
            report_dir, rating = self.runner(run, emit)
            run.report_id, run.rating = Path(report_dir).name, rating
            run.status = "completed"
            emit("done", {"report_id": run.report_id, "rating": rating})
        except Exception as e:  # noqa: BLE001 — a failed run is reported, never raised into the pool
            run.status, run.error = "failed", f"{type(e).__name__}: {e}"
            emit("error", {"message": run.error, "trace": traceback.format_exc(limit=5)})
        finally:
            run.finished = datetime.now().isoformat(timespec="seconds")
            emit("status", {"status": run.status})

    @staticmethod
    def wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
        """Poll ``predicate`` until it holds (tests)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()
