"""The web server: runs queued from a ticker, their live events, and saved reports.

Offline: the analysis runner is a stub, and reports live in a temporary folder.
"""
from __future__ import annotations

import io
import json
import threading
import types
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


PREFS = {"llm_provider": "deepseek", "quick_think_llm": "deepseek-v4-pro", "deep_think_llm": "deepseek-v4-pro",
         "research_depth": 5, "output_language": "Chinese", "analysts": ["market", "social", "news", "fundamentals"]}


@pytest.fixture(autouse=True)
def prefs(tmp_path, monkeypatch):
    """A temporary prefs file (never the real one) and a DeepSeek key, so options validate."""
    path = tmp_path / "cli_prefs.json"
    path.write_text(json.dumps(PREFS))
    monkeypatch.setattr(settings, "PREFS_PATH", path)
    monkeypatch.setattr(settings, "get_current_date", lambda: TODAY)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    for var in ("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "TRADINGAGENTS_MAX_RISK_ROUNDS", "TRADINGAGENTS_LLM_BACKEND_URL"):
        monkeypatch.delenv(var, raising=False)
    return path


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


def test_options_default_to_the_last_run_and_mark_missing_keys():
    o = settings.options()
    d = o["defaults"]
    assert d["llm_provider"] == "deepseek" and d["deep_think_llm"] == "deepseek-v4-pro" and d["research_depth"] == 5
    assert d["date"] == TODAY and d["output_language"] == "Chinese"
    by = {p["key"]: p for p in o["providers"]}
    assert by["deepseek"]["key_set"] and not by["openai"]["key_set"] and by["openai"]["key_env"] == "OPENAI_API_KEY"
    assert "qwen-cn" in by and "chatgpt" not in by and by["ollama"]["url_editable"]
    assert by["openai"]["effort"]["config_key"] == "openai_reasoning_effort"
    assert [x["value"] for x in o["depths"]] == [1, 3, 5]


@pytest.mark.parametrize("bad, message", [
    ({"date": "2099-01-01"}, "不能晚于今天"),
    ({"date": "2026-13-01"}, "格式"),
    ({"analysts": []}, "至少选择一位分析师"),
    ({"analysts": ["oracle"]}, "至少选择一位分析师"),
    ({"research_depth": 2}, "1、3 或 5"),
    ({"llm_provider": "chatgpt"}, "不支持"),
    ({"llm_provider": "openai"}, "OPENAI_API_KEY"),
    ({"quick_think_llm": "rm -rf /"}, "模型名不合法"),
    ({"llm_provider": "ollama", "backend_url": "ftp://x"}, "http"),
])
def test_bad_options_are_refused_with_a_reason(bad, message):
    with pytest.raises(ValueError, match=message):
        settings.validate(bad)


def test_options_become_the_run_config(monkeypatch):
    opts = settings.validate({"analysts": ["news", "market"], "research_depth": 3, "date": "2026-11-13",
                              "output_language": "Japanese"})
    config, analysts = settings.run_config(opts)
    assert analysts == ["market", "news"], "in the graph's order"
    assert config["llm_provider"] == "deepseek" and config["deep_think_llm"] == "deepseek-v4-pro"
    assert config["backend_url"] == "https://api.deepseek.com"
    assert config["max_debate_rounds"] == config["max_risk_discuss_rounds"] == 3
    assert config["output_language"] == "Japanese"
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    o = settings.validate({"llm_provider": "openai", "effort": "high"})
    assert o.quick_think_llm and o.effort == "high"
    assert settings.run_config(o)[0]["openai_reasoning_effort"] == "high"
    # Set before the server started: DEFAULT_CONFIG already carries it.
    monkeypatch.setenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "2")
    monkeypatch.setitem(settings.DEFAULT_CONFIG, "max_debate_rounds", 2)
    assert settings.run_config(opts)[0]["max_debate_rounds"] == 2, "the environment wins, as in the CLI"


def test_a_started_run_carries_its_options_and_is_remembered(env, prefs):
    client, manager, _, gate = env
    r = client.post("/api/runs", json={"ticker": "300308", "options": {"date": "2026-11-13", "research_depth": 1,
                                                                      "analysts": ["market"]}})
    assert r.status_code == 201
    run = r.json()
    assert run["trade_date"] == "2026-11-13" and run["options"]["research_depth"] == 1
    assert run["options"]["analysts"] == ["market"]
    gate.set()
    saved = json.loads(prefs.read_text())
    assert saved["research_depth"] == 1 and saved["analysts"] == ["market"] and saved["llm_provider"] == "deepseek"
    bad = client.post("/api/runs", json={"ticker": "300308", "options": {"llm_provider": "openai"}})
    assert bad.status_code == 400 and "OPENAI_API_KEY" in bad.json()["detail"]
    assert client.get("/api/options").json()["defaults"]["research_depth"] == 1


# ---------------------------------------------------------------------------
# Market, search and name resolution
# ---------------------------------------------------------------------------
@pytest.fixture
def mkt(tmp_path, monkeypatch):
    import pandas as pd

    from tradingagents.dataflows.vendors.akshare import settings as ak_settings, store
    from web.server import market

    data = tmp_path / ".akshare_data"
    ak_settings.set_data_dir(data)
    for day, pct in (("20261112", 1.0), ("20261113", -8.391)):
        (data / "snapshots" / day).mkdir(parents=True)
        pd.DataFrame({"trade_date": pd.Timestamp(day), "code": ["300308", "600519", "000001", "002142"],
                      "exchange": ["SZ", "SH", "SZ", "SZ"], "name": ["中际旭创", "贵州茅台", "平安银行", "宁波银行"],
                      "open": 1.0, "high": 2.0, "low": 0.5,
                      "pct_chg": [pct, 1.77, 0.1, 0.2], "close": [466.2, 1435.26, 11.0, 25.0], "turnover": [4.83, 0.33, 0.5, 0.6],
                      "amount": [2.59e10, 5.95e9, 1e9, 1e9], "volume": [536097.14, 41779.84, 1e5, 1e5],
                      "total_mv": [5.49e11, 1.79e12, 2e11, 1.6e11]}).to_parquet(data / "snapshots" / day / "cross_section.parquet")
    pd.DataFrame({"证券代码": ["300308", "600519"], "行业代码": ["801770", "801120"]}).to_pickle(data / "sw_comp__2026W46.pkl")
    pd.DataFrame({"行业代码": ["801770.SI", "801120.SI"], "行业名称": ["通信", "食品饮料"]}).to_pickle(data / "sw_first__2026W46.pkl")
    pd.DataFrame({"证券代码": ["600519"], "二级代码": ["801125"]}).to_pickle(data / "sw_second_cons__2026W46.pkl")
    pd.DataFrame({"行业代码": ["801125.SI"], "行业名称": ["白酒Ⅱ"]}).to_pickle(data / "sw_second__2026W46.pkl")
    for f in (market._read_xs, market.industries):
        f.cache_clear()
    market._TABLES.clear()
    monkeypatch.setattr(store, "last_closed_trade_date", lambda now=None: pd.Timestamp("2026-11-13").date())
    monkeypatch.setattr(store, "is_intraday", lambda now=None: False)
    fake = types.SimpleNamespace()
    monkeypatch.setattr(store, "ak", lambda: fake)
    yield market, fake, data
    for f in (market._read_xs, market.industries):
        f.cache_clear()
    market._TABLES.clear()
    ak_settings.set_data_dir(None)


def _boom(*a, **k):
    raise ConnectionError("rate limited")


def test_the_market_table_joins_industry_and_eastmoney_main_flow(mkt):
    import pandas as pd

    market, fake, _ = mkt
    fake.stock_individual_fund_flow_rank = lambda indicator: pd.DataFrame(
        {"代码": ["300308", "600519"], "今日主力净流入-净额": [-1.2e9, 3.4e8]})
    table = market.market_table()
    assert table["date"] == "2026-11-13" and table["dates"] == ["2026-11-13", "2026-11-12"] and table["count"] == 4
    assert table["flow"]["source"] == "eastmoney" and table["flow"]["label"] == "主力净流入"
    row = {r["code"]: r for r in table["rows"]}
    assert row["300308"]["industry"] == "通信" and row["300308"]["main_flow"] == -1.2e9 and row["300308"]["pct_chg"] == -8.391
    assert row["600519"]["sub_industry"] == "白酒Ⅱ" and row["000001"]["industry"] is None


def test_without_eastmoney_the_flow_is_ths_and_labelled_so(mkt):
    import pandas as pd

    market, fake, _ = mkt
    fake.stock_individual_fund_flow_rank = _boom
    fake.stock_fund_flow_individual = lambda symbol: pd.DataFrame({"股票代码": ["300308"], "净额": ["-5.33亿"]})
    table = market.market_table()
    assert table["flow"]["source"] == "ths" and "同花顺" in table["flow"]["label"] and "不能与主力净流入比较" in table["flow"]["note"]
    assert {r["code"]: r["main_flow"] for r in table["rows"]}["300308"] == pytest.approx(-5.33e8)
    older = market.market_table("2026-11-12")
    assert older["flow"]["source"] is None and "只有最新交易日" in older["flow"]["note"]


def test_names_resolve_to_codes_and_ambiguity_is_explained(mkt):
    market, _, _ = mkt
    assert market.resolve_ticker("中际旭创") == "300308" and market.resolve_ticker("茅台") == "600519"
    assert market.resolve_ticker("300308") == "300308" and market.resolve_ticker("NVDA") == "NVDA"
    with pytest.raises(ValueError, match="平安银行\\(000001\\)、宁波银行\\(002142\\)"):
        market.resolve_ticker("银行")
    with pytest.raises(ValueError, match="找不到"):
        market.resolve_ticker("不存在")
    assert [s["code"] for s in market.search("3003")] == ["300308"]
    assert market.search("茅台")[0]["symbol"] == "600519.SS"


def test_a_run_started_by_name_and_the_market_endpoints(mkt, env):
    import pandas as pd

    _, fake, _ = mkt
    client, manager, _, gate = env
    fake.stock_individual_fund_flow_rank = lambda indicator: pd.DataFrame({"代码": ["300308"], "今日主力净流入-净额": [1.0]})
    run = client.post("/api/runs", json={"ticker": "中际旭创"}).json()
    assert run["symbol"] == "300308.SZ"
    gate.set()
    r = client.post("/api/runs", json={"ticker": "银行"})
    assert r.status_code == 400 and "对应多只股票" in r.json()["detail"]
    assert client.get("/api/market").json()["count"] == 4
    assert client.get("/api/market?date=2026-01-01").status_code == 404
    assert client.get("/api/stocks/search?q=茅台").json()[0]["code"] == "600519"
    assert client.get("/api/stocks/300308").json()["industry"] == "通信"
    assert client.get("/api/stocks/999999").status_code == 404


def test_a_stock_s_whole_history_from_the_local_store(mkt):
    import json as _json

    import pandas as pd

    market, _, data = mkt
    from tradingagents.dataflows.vendors.akshare import snapshots

    base = data / "snapshots" / "base"
    base.mkdir(parents=True)
    cols = snapshots.COLUMNS
    hist = pd.DataFrame({c: [None, None] for c in cols})
    hist["trade_date"] = pd.to_datetime(["2012-04-10", "2026-11-11"])
    hist["code"], hist["exchange"], hist["name"], hist["source"] = "300308", "SZ", "中际旭创", "hist"
    for c, v in (("open", 20.5), ("high", 21.8), ("low", 20.5), ("close", 21.8), ("volume", 82199.0), ("amount", 1.7e8)):
        hist[c] = v
    hist.to_parquet(base / "SZ300308.parquet")
    (data / "snapshots" / "_meta.json").write_text(_json.dumps({"layout": snapshots.LAYOUT, "base_through": "20261111"}))
    snapshots._SRC_CACHE = None
    h = market.history("300308")
    assert h["source"] == "snapshot" and h["adjust"] == "不复权" and h["volume_unit"] == "手"
    assert h["base_through"] == "2026-11-11" and h["bars"][0]["time"] == "2012-04-10"
    assert h["bars"][-1]["time"] == "2026-11-13" and h["after_base"] == 2, "base, then the daily cross-sections after it"
    assert [b["time"] for b in market.history("300308", "2026-11-12")["bars"]][-1] == "2026-11-12"
    with pytest.raises(FileNotFoundError):
        market.history("AAPL")
