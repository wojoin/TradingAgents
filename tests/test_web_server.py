"""The web server: runs queued from a ticker, their live events, and saved reports.

Offline: the analysis runner is a stub, and reports live in a temporary folder.
"""
from __future__ import annotations

import io
import json
import threading
import zipfile

import pytest
from fastapi.testclient import TestClient

from web.server import settings
from web.server.app import create_app
from web.server.runs import Progress, Run, RunManager

pytestmark = pytest.mark.unit

TODAY = "2026-11-15"


def write_report(root, name="300308.SZ_20261115_012528", rating="Overweight"):
    d = root / name
    (d / "1_analysts").mkdir(parents=True)
    (d / "5_portfolio").mkdir()
    (d / "1_analysts" / "market.md").write_text("## 技术分析\n均线空头排列", encoding="utf-8")
    (d / "5_portfolio" / "decision.md").write_text("**Rating**: Overweight", encoding="utf-8")
    (d / "complete_report.md").write_text(
        f"# Trading Analysis Report: 300308.SZ\n\n- Analysis date: 2026-11-15\n- Rating: {rating}\n"
        "- Generated: 2026-11-15 01:35:44\n- TradingAgents 0.7.1: deepseek, deep deepseek-v4-pro, quick deepseek-v4-pro\n",
        encoding="utf-8")
    (d / "complete_report.html").write_text("<html>report</html>", encoding="utf-8")
    return d


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "reports"
    root.mkdir()
    gate = threading.Event()

    def runner(run, emit):
        emit("tool", {"name": "get_stock_data"})
        emit("section", {"key": "market_report", "title": "市场/技术分析", "content": "上涨"})
        gate.wait(5)
        if run.ticker == "BOOM":
            raise RuntimeError("model unavailable")
        return write_report(root, f"{run.symbol}_x"), "Overweight"

    manager = RunManager(runner=runner, today=lambda: TODAY)
    client = TestClient(create_app(manager, reports_root=root))
    return client, manager, root, gate


def test_a_run_needs_only_a_ticker_and_is_normalized(env):
    client, manager, _, gate = env
    r = client.post("/api/runs", json={"ticker": " 300308 "})
    assert r.status_code == 201
    run = r.json()
    assert run["symbol"] == "300308.SZ" and run["trade_date"] == TODAY and run["status"] in ("queued", "running")
    gate.set()
    assert manager.wait_until(lambda: manager.get(run["id"]).status == "completed")
    done = client.get(f"/api/runs/{run['id']}").json()
    assert done["report_id"] == "300308.SZ_x" and done["rating"] == "Overweight"
    assert client.get("/api/runs").json()[0]["id"] == run["id"]


@pytest.mark.parametrize("bad", ["", "../etc", "a b", "x" * 21])
def test_a_bad_ticker_is_refused(env, bad):
    assert env[0].post("/api/runs", json={"ticker": bad}).status_code == 400


def test_events_stream_in_order_and_resume_after_the_last_seen(env):
    client, manager, _, gate = env
    run_id = client.post("/api/runs", json={"ticker": "300308"}).json()["id"]
    gate.set()
    assert manager.wait_until(lambda: manager.get(run_id).status == "completed")
    body = client.get(f"/api/runs/{run_id}/events").text
    kinds = [line.split(": ", 1)[1] for line in body.splitlines() if line.startswith("event: ")]
    assert kinds == ["status", "status", "tool", "section", "done", "status"]
    assert '"content": "上涨"' in body, "Chinese text is sent as is"
    tail = client.get(f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "4"}).text
    assert [line for line in tail.splitlines() if line.startswith("event: ")] == ["event: done", "event: status"]


def test_a_failed_run_says_why(env):
    client, manager, _, gate = env
    run_id = client.post("/api/runs", json={"ticker": "BOOM"}).json()["id"]
    gate.set()
    assert manager.wait_until(lambda: manager.get(run_id).status == "failed")
    assert "model unavailable" in client.get(f"/api/runs/{run_id}").json()["error"]
    assert "event: error" in client.get(f"/api/runs/{run_id}/events").text


def test_reports_are_listed_read_and_downloaded(env):
    client, _, root, _ = env
    write_report(root)
    (root / "not_a_report").mkdir()
    listing = client.get("/api/reports").json()
    assert [r["id"] for r in listing] == ["300308.SZ_20261115_012528"]
    meta = listing[0]
    assert meta["ticker"] == "300308.SZ" and meta["rating"] == "Overweight" and meta["analysis_date"] == "2026-11-15"
    report = client.get("/api/reports/300308.SZ_20261115_012528").json()
    assert [s["folder"] for s in report["sections"]] == ["1_analysts", "5_portfolio"]
    assert report["sections"][0]["agents"][0]["content"].endswith("均线空头排列")
    md = client.get("/api/reports/300308.SZ_20261115_012528/download?format=md")
    assert md.headers["content-disposition"].startswith("attachment") and "300308.SZ_20261115_012528.md" in \
        md.headers["content-disposition"]
    html = client.get("/api/reports/300308.SZ_20261115_012528/download?format=html&inline=1")
    assert html.headers["content-disposition"].startswith("inline") and html.text == "<html>report</html>"
    z = zipfile.ZipFile(io.BytesIO(client.get("/api/reports/300308.SZ_20261115_012528/download?format=zip").content))
    assert "300308.SZ_20261115_012528/1_analysts/market.md" in z.namelist()


@pytest.mark.parametrize("bad", ["..%2Freports", "..%2F..%2Fmemory", "nope", "not_a_report"])
def test_a_report_id_resolves_only_to_a_saved_report(env, bad):
    client, _, root, _ = env
    write_report(root)
    (root / "not_a_report").mkdir(exist_ok=True)
    assert client.get(f"/api/reports/{bad}").status_code == 404
    assert client.get(f"/api/reports/{bad}/download?format=zip").status_code == 404
    assert client.get("/api/reports/300308.SZ_20261115_012528/download?format=exe").status_code == 422


def test_progress_follows_the_graph_through_each_team():
    events = []
    run = Run(id="r", ticker="300308", symbol="300308.SZ", trade_date=TODAY)
    p = Progress(run, lambda k, d: events.append((k, d)), ["market", "news"])
    assert run.agents["Market Analyst"] == "in_progress" and "Sentiment Analyst" not in run.agents
    p.update({"market_report": "m"})
    p.update({"investment_debate_state": {"bull_history": "b", "bear_history": ""}})
    p.update({"investment_plan": "plan"})
    p.update({"trader_investment_plan": "t", "risk_debate_state": {"neutral_history": "n"}})
    p.update({"final_trade_decision": "d"})
    p.update({"market_report": "m"})                      # unchanged: no repeat event
    assert run.agents["Market Analyst"] == run.agents["Bull Researcher"] == run.agents["Portfolio Manager"] == "completed"
    assert run.agents["News Analyst"] == "in_progress"
    sections = [d["key"] for k, d in events if k == "section"]
    assert sections == ["market_report", "bull_history", "investment_plan", "trader_investment_plan",
                        "neutral_history", "final_trade_decision"]


def test_a_web_run_takes_the_cli_s_last_choices(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", raising=False)
    monkeypatch.setenv("TRADINGAGENTS_MAX_RISK_ROUNDS", "2")
    prefs = tmp_path / "prefs.json"
    prefs.write_text(json.dumps({"llm_provider": "DeepSeek", "deep_think_llm": "deepseek-v4-pro",
                                 "quick_think_llm": "deepseek-v4-pro", "research_depth": 5,
                                 "output_language": "Chinese", "analysts": ["news", "market"]}))
    config, analysts = settings.run_config(settings.load_prefs(prefs))
    assert config["llm_provider"] == "deepseek" and config["deep_think_llm"] == "deepseek-v4-pro"
    assert config["max_debate_rounds"] == 5 and config["output_language"] == "Chinese"
    assert analysts == ["market", "news"], "in the graph's order"
    assert settings.load_prefs(tmp_path / "missing.json") == {}
    assert settings.run_config({})[1] == ["market", "social", "news", "fundamentals"]
