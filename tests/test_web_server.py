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
    monkeypatch.setattr(store.time, "sleep", lambda s: None)      # no real waits between retries
    fake = types.SimpleNamespace()
    monkeypatch.setattr(store, "ak", lambda: fake)
    yield market, fake, data
    for f in (market._read_xs, market.industries, market._history_day, market.pct_5d, market._ttm):
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


# ---------------------------------------------------------------------------
# Watchlist (自选)
# ---------------------------------------------------------------------------
def test_watchlist_groups_have_names_colours_and_stocks(tmp_path):
    from web.server import watchlist

    path = tmp_path / "watchlist.json"
    assert [g["id"] for g in watchlist.load(path)] == ["default"], "the default group always exists"
    tech = watchlist.create_group("科技", "#E5484D", path)
    assert tech["color"] == "#e5484d" and tech["codes"] == []
    liquor = watchlist.create_group("白酒", path=path)
    watchlist.add_stock(tech["id"], "300308", path)
    watchlist.add_stock(tech["id"], "600519.SH", path)
    watchlist.add_stock(liquor["id"], "600519", path)
    assert watchlist.add_stock(tech["id"], "300308", path)["codes"] == ["300308", "600519"], "no duplicates"
    assert watchlist.all_codes(watchlist.load(path)) == ["300308", "600519"]
    with pytest.raises(ValueError, match="只支持 A 股"):
        watchlist.add_stock(tech["id"], "AAPL", path)
    with pytest.raises(ValueError, match="已有名为"):
        watchlist.create_group("科技", path=path)
    with pytest.raises(ValueError, match="1 到 20"):
        watchlist.create_group("", path=path)
    with pytest.raises(ValueError, match="#RRGGBB"):
        watchlist.update_group(tech["id"], color="red", path=path)
    assert watchlist.update_group(tech["id"], name="通信", color="#16a34a", path=path)["name"] == "通信"
    assert watchlist.remove_stock(tech["id"], "600519.SS", path)["codes"] == ["300308"]
    assert [g["name"] for g in watchlist.delete_group(liquor["id"], path)] == ["默认", "通信"]
    with pytest.raises(KeyError):
        watchlist.add_stock("nope", "300308", path)


def test_at_most_256_groups(tmp_path, monkeypatch):
    from web.server import watchlist

    path = tmp_path / "w.json"
    monkeypatch.setattr(watchlist, "MAX_GROUPS", 3)
    for i in range(2):                     # with the default group, three
        watchlist.create_group(f"g{i}", path=path)
    with pytest.raises(ValueError, match="最多只能有 3 个分组"):
        watchlist.create_group("g2", path=path)
    assert watchlist.MAX_GROUPS == 3 and len(watchlist.load(path)) == 3


def test_a_watchlist_from_before_groups_becomes_the_default_group(tmp_path):
    from web.server import watchlist

    path = tmp_path / "w.json"
    path.write_text(json.dumps({"codes": ["300308", "AAPL", "600519"]}))
    [g] = watchlist.load(path)
    assert g["name"] == "默认" and g["codes"] == ["300308", "600519"]
    assert g["id"] == "default" and watchlist.load(path)[0]["id"] == "default", "the same id on every read"
    assert watchlist.add_stock("default", "000001", path)["codes"] == ["300308", "600519", "000001"]
    assert json.loads(path.read_text())["groups"][0]["id"] == "default", "written in the grouped form"
    path.write_text("not json")
    assert [g["id"] for g in watchlist.load(path)] == ["default"]


def test_the_default_group_cannot_be_deleted_and_comes_first(tmp_path):
    from web.server import watchlist

    path = tmp_path / "w.json"
    path.write_text(json.dumps({"groups": [{"id": "x1", "name": "默认", "codes": ["300308"]}]}))
    groups = watchlist.load(path)
    assert [g["id"] for g in groups] == ["default", "x1"] and groups[0]["name"] == "默认分组", "no clash of names"
    with pytest.raises(ValueError, match="默认分组不可删除"):
        watchlist.delete_group("default", path)
    with pytest.raises(ValueError, match="默认分组不可修改"):
        watchlist.update_group("default", name="我的自选", path=path)
    with pytest.raises(ValueError, match="默认分组不可修改"):
        watchlist.update_group("default", color="#16a34a", path=path)


def test_stocks_move_to_the_top_or_bottom_of_their_group(tmp_path):
    from web.server import watchlist

    path = tmp_path / "w.json"
    for c in ("300308", "600519", "000001"):
        watchlist.add_stock("default", c, path)
    assert watchlist.move_stock("default", "000001", "top", path)["codes"] == ["000001", "300308", "600519"]
    assert watchlist.move_stock("default", "000001", "bottom", path)["codes"] == ["300308", "600519", "000001"]
    with pytest.raises(ValueError, match="不在这个分组"):
        watchlist.move_stock("default", "002142", "top", path)
    with pytest.raises(ValueError, match="最前"):
        watchlist.move_stock("default", "300308", "middle", path)


def test_a_note_belongs_to_the_stock_in_every_group(tmp_path):
    from web.server import watchlist

    path = tmp_path / "w.json"
    tech = watchlist.create_group("科技", path=path)
    watchlist.add_stock("default", "300308", path)
    watchlist.add_stock(tech["id"], "300308", path)
    note = watchlist.set_note("300308.SZ", "  光模块龙头，关注 1.6T 放量  ", path)
    assert note["text"] == "光模块龙头，关注 1.6T 放量" and note["updated"]
    assert watchlist.notes(path) == {"300308": note}, "one note per stock, whatever the group"
    watchlist.remove_stock("default", "300308", path)
    assert "300308" in watchlist.notes(path), "removing from a group keeps the note"
    assert watchlist.set_note("300308", "", path) is None and watchlist.notes(path) == {}
    with pytest.raises(ValueError, match="最多 2000"):
        watchlist.set_note("300308", "x" * 2001, path)
    with pytest.raises(ValueError, match="只支持 A 股"):
        watchlist.set_note("AAPL", "x", path)


def test_watch_rows_add_the_day_s_range_and_ttm_earnings(mkt, tmp_path):
    import pandas as pd

    market, fake, data = mkt
    fake.stock_individual_fund_flow_rank = lambda indicator: pd.DataFrame({"代码": ["300308"], "今日主力净流入-净额": [1e8]})
    xs = data / "snapshots" / "20261113" / "cross_section.parquet"
    df = pd.read_parquet(xs)
    df["pre_close"], df["open"], df["high"], df["low"], df["amplitude"] = 500.0, 510.0, 525.0, 461.71, 12.4
    df["close"], df["total_mv"], df["float_mv"] = 466.2, 466.2 * 1e9, 466.2 * 8e8
    df.to_parquet(xs)
    market._read_xs.cache_clear()
    pd.DataFrame({"股票代码": ["300308"], "净利润-净利润": [22e9]}).to_pickle(data / "yjbb__P20260930.pkl")
    pd.DataFrame({"股票代码": ["300308"], "净利润-净利润": [7e9]}).to_pickle(data / "yjbb_hist_20250930__P20250930.pkl")
    asked = []
    fake.stock_yjbb_em = lambda date: asked.append(date) or pd.DataFrame(
        {"股票代码": ["300308"], "净资产收益率": [1.0], "净利润-同比增长": [1.0], "净利润-净利润": [10e9]})
    market._ttm.cache_clear()
    profit, label = market.ttm_profit()
    assert asked == ["20251231"] and profit["300308"] == pytest.approx(25e9) and "2026 三季报" in label
    w = market.watch_rows(["300308", "999999"])
    r = w["rows"][0]
    assert r["open_pct"] == pytest.approx(2.0) and r["high"] == 525.0 and r["amplitude"] == 12.4
    assert r["total_shares"] == pytest.approx(1e9) and r["float_shares"] == pytest.approx(8e8)
    assert r["eps_ttm"] == pytest.approx(25.0) and r["pe_ttm"] == pytest.approx(466.2 / 25)
    assert r["pct_5d"] is None, "fewer than six sessions on record"
    assert w["rows"][1] == {"code": "999999", "name": None, "missing": True}
    market._ttm.cache_clear()


def test_the_watchlist_endpoints(mkt, tmp_path):
    import pandas as pd

    _, fake, _ = mkt
    fake.stock_individual_fund_flow_rank = lambda indicator: pd.DataFrame({"代码": ["300308"], "今日主力净流入-净额": [1.0]})
    client = TestClient(create_app(RunManager(runner=lambda r, e: None), reports_root=tmp_path,
                                   watchlist_path=tmp_path / "w.json"))
    g = client.post("/api/watchlist/groups", json={"name": "科技", "color": "#e5484d"})
    assert g.status_code == 201
    gid = g.json()["id"]
    assert client.post("/api/watchlist/groups", json={"name": "科技"}).status_code == 400
    assert client.put(f"/api/watchlist/groups/{gid}/stocks/300308").json()["codes"] == ["300308"]
    assert client.put(f"/api/watchlist/groups/{gid}/stocks/AAPL").status_code == 400
    assert client.put("/api/watchlist/groups/nope/stocks/300308").status_code == 404
    assert client.post(f"/api/watchlist/groups/{gid}/stocks/300308/move", json={"to": "top"}).status_code == 200
    assert client.put("/api/watchlist/notes/300308", json={"text": "龙头"}).json()["note"]["text"] == "龙头"
    assert client.delete("/api/watchlist/groups/default").status_code == 400
    body = client.get("/api/watchlist").json()
    assert body["groups"][1]["codes"] == ["300308"] and body["max_groups"] == 256
    assert body["notes"]["300308"]["text"] == "龙头"
    assert body["rows"]["300308"]["name"] == "中际旭创" and body["date"] == "2026-11-13"
    assert client.patch(f"/api/watchlist/groups/{gid}", json={"color": "#16a34a"}).json()["color"] == "#16a34a"
    assert client.delete(f"/api/watchlist/groups/{gid}/stocks/300308").json()["codes"] == []
    assert [g["id"] for g in client.delete(f"/api/watchlist/groups/{gid}").json()["groups"]] == ["default"]
    assert client.get("/api/watchlist?rows=0").json()["max_groups"] == 256


def _history_store(data, monkeypatch, store, market):
    """base history for 300308 (2026-11-03..06) beside the fixture's daily days 11-12 and 11-13."""
    import json as _json

    import pandas as pd

    from tradingagents.dataflows.vendors.akshare import snapshots

    base = data / "snapshots" / "base"
    base.mkdir(parents=True)
    days = ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    hist = pd.DataFrame({c: [None] * 4 for c in snapshots.COLUMNS})
    hist["trade_date"] = pd.to_datetime(days)
    hist["code"], hist["exchange"], hist["name"], hist["source"] = "300308", "SZ", "中际旭创", "hist"
    hist["pct_chg"] = [10.0, 10.0, 10.0, 1.0]
    hist["open"] = hist["high"] = hist["low"] = hist["close"] = 100.0
    hist["volume"], hist["turnover"] = 1000.0, 2.0
    hist.to_parquet(base / "SZ300308.parquet")
    (data / "snapshots" / "_meta.json").write_text(
        _json.dumps({"layout": snapshots.LAYOUT, "base_through": "20261106"}))
    snapshots._SRC_CACHE = None
    # trading days: the four in base, then 11-12 and 11-13 (11-09..11 are not on this calendar)
    monkeypatch.setattr(store, "_CAL", pd.DatetimeIndex(pd.to_datetime([*days, "2026-11-12", "2026-11-13"])))
    for f in (market._read_xs, market._history_day, market.pct_5d):
        f.cache_clear()


def test_the_5_day_change_compounds_five_trading_days_across_base_and_daily(mkt, monkeypatch):
    from tradingagents.dataflows.vendors.akshare import store

    market, _, data = mkt
    _history_store(data, monkeypatch, store, market)
    five = market.pct_5d("2026-11-13")         # 11-04, 11-05, 11-06 from base; 11-12, 11-13 daily
    assert five["300308"] == pytest.approx((1.1 * 1.1 * 1.01 * 1.01 * (1 - 0.08391) - 1) * 100)
    assert five["600519"] == pytest.approx((1.0177 ** 2 - 1) * 100), "no row on a day: unchanged that day"
    assert market.pct_5d("2026-11-06") is None, "fewer than five trading days on the calendar"


def test_a_historical_day_comes_from_base(mkt, monkeypatch):
    from tradingagents.dataflows.vendors.akshare import store

    market, _, data = mkt
    _history_store(data, monkeypatch, store, market)
    table = market.market_table("2026-11-05")
    assert table["date"] == "2026-11-05" and table["breadth"] == {"total": 1, "up": 1, "down": 0, "flat": 0}
    r = table["rows"][0]
    assert r["code"] == "300308" and r["pct_chg"] == 10.0 and r["main_flow"] is None
    assert r["float_shares"] == pytest.approx(1000 * 1e4 / 2.0), "from the day's turnover"
    assert r["total_mv"] is None and r["pe_ttm"] is None and "历史行情不含总股本" in table["note"]
    assert (data / "web" / "xs" / "20261105.parquet").exists(), "cached on disk"
    with pytest.raises(FileNotFoundError):
        market.market_table("2026-11-08")
    cal = market.calendar()
    assert cal["min"] == "2026-11-03" and cal["max"] == "2026-11-13"
    assert cal["holidays"] == ["2026-11-09", "2026-11-10", "2026-11-11"]


def test_market_stats_count_rises_and_falls_and_sum_the_amount_day_by_day(mkt, monkeypatch, tmp_path):
    from tradingagents.dataflows.vendors.akshare import store

    market, _, data = mkt
    _history_store(data, monkeypatch, store, market)
    market._daily_stats.cache_clear()
    st = market.market_stats("2026-11-13", "60d")
    assert st["end"] == "2026-11-13" and [d["date"] for d in st["days"]] == [
        "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-12", "2026-11-13"]
    by = {d["date"]: d for d in st["days"]}
    assert by["2026-11-05"] == {"date": "2026-11-05", "up": 1, "down": 0, "flat": 0, "total": 1, "amount": 0.0,
                                "median": 10.0, "limit_up": 0, "limit_down": 0, "broken": 0}
    assert (by["2026-11-13"]["up"], by["2026-11-13"]["down"], by["2026-11-13"]["total"]) == (3, 1, 4)
    assert by["2026-11-12"]["amount"] == pytest.approx(2.59e10 + 5.95e9 + 2e9)
    assert (data / "web" / "market_stats_v3.parquet").exists() and (data / "web" / "limit_events_v3.parquet").exists()
    assert [d["date"] for d in market.market_stats("2026-11-13", "1d")["days"]] == ["2026-11-13"]
    assert market.market_stats("2026-11-10", "1d")["end"] == "2026-11-06", "the last day with data on or before"
    with pytest.raises(ValueError):
        market.market_stats(None, "2y")
    client = TestClient(create_app(RunManager(runner=lambda r, e: None), reports_root=tmp_path, watchlist_path=tmp_path / "w.json"))
    assert client.get("/api/market/stats?range=1y&end=2026-11-13").json()["start"] == "2025-11-13"
    assert client.get("/api/market/stats?range=2y").status_code == 400
    assert by["2026-11-13"]["median"] == pytest.approx(0.15)
    assert st["indexes"] == {} and "指数行情获取失败" in st["index_error"], "no index source in the fake"
    market._daily_stats.cache_clear()


@pytest.mark.parametrize("code, name, day, rate", [
    ("600519", "贵州茅台", "2026-11-13", 0.10), ("600001", "ST某某", "2026-07-03", 0.05),
    ("600001", "*ST某某", "2026-07-06", 0.10), ("300308", "中际旭创", "2026-11-13", 0.20),
    ("300001", "ST创业", "2026-01-05", 0.20), ("300308", "中际旭创", "2020-08-21", 0.10),
    ("688981", "中芯国际", "2026-11-13", 0.20), ("920489", "佳先股份", "2026-11-13", 0.30),
    ("830799", "艾融软件", "2026-11-13", 0.30),
])
def test_price_limits_by_board_st_and_date(code, name, day, rate):
    import pandas as pd

    from web.server import market

    got = market.limit_rate(pd.Series([code]), pd.Series([name]), pd.Series([day]))
    assert got.iat[0] == pytest.approx(rate)


def test_limit_moves_round_like_the_exchanges_and_skip_unlimited_days():
    import pandas as pd

    from web.server import market

    rows = pd.DataFrame({
        "trade_date": "2026-11-17",
        "code": ["600770", "920489", "920309", "000701", "600156", "000635", "600519"],
        "name": ["综艺股份", "佳先股份", "N菊乐", "厦门信达", "华升股份", "英力特", "贵州茅台"],
        "pre_close": [5.03, 9.65, 31.92, 5.81, 7.15, 11.0, 1400.0],
        "close": [5.53, 12.54, 56.78, 5.23, 7.35, 0.0, 1410.0],
        "high": [5.53, 12.54, 70.02, 5.75, 7.87, 0.0, 1420.0],
        "pct_chg": [9.94, 29.948, 77.882, -9.983, 2.797, 0.0, 0.714],
        "amount": 1e8,
    })
    stats, events = market._stats_of(rows)
    kinds = dict(zip(events["code"], events["kind"], strict=False))
    # 5.03 x 1.1 = 5.533 -> 5.53; Beijing cuts 12.545 to 12.54; a new listing has no limit;
    # 5.81 x 0.9 = 5.229 -> 5.23; 7.15 x 1.1 = 7.865 -> 7.87 touched and lost; suspended skipped.
    assert kinds == {"600770": "up", "920489": "up", "000701": "down", "600156": "broken"}
    assert stats.iloc[0][["limit_up", "limit_down", "broken"]].tolist() == [2, 1, 1]


def test_the_limit_board_counts_days_in_a_row(mkt, monkeypatch, tmp_path):
    import pandas as pd

    from tradingagents.dataflows.vendors.akshare import store

    market, _, data = mkt
    _history_store(data, monkeypatch, store, market)
    # 300308 closes at the limit on both daily days (2 in a row), 600519 touches it on
    # 11-13 and falls back, 000001 closes at the lower limit.
    for day, rows in {
        "20261112": [("300308", 100.0, 120.0, 120.0, 20.0), ("600519", 100.0, 101.0, 101.0, 1.0),
                     ("000001", 10.0, 10.1, 10.1, 1.0), ("002142", 20.0, 20.0, 20.0, 0.0)],
        "20261113": [("300308", 120.0, 144.0, 144.0, 20.0), ("600519", 101.0, 105.0, 111.1, 3.96),
                     ("000001", 10.1, 9.09, 10.1, -10.0), ("002142", 20.0, 20.2, 20.2, 1.0)],
    }.items():
        pd.DataFrame({"trade_date": pd.Timestamp(day), "code": [r[0] for r in rows],
                      "name": ["中际旭创", "贵州茅台", "平安银行", "宁波银行"],
                      "pre_close": [r[1] for r in rows], "close": [r[2] for r in rows], "high": [r[3] for r in rows],
                      "pct_chg": [r[4] for r in rows], "amount": 1e9, "volume": 1e5, "turnover": 1.0,
                      # 300308 opens at the limit on 11-13 and stays there: 一字板.
                      "open": [r[2] if day == "20261113" and r[0] == "300308" else r[1] for r in rows],
                      "low": [r[2] if day == "20261113" and r[0] == "300308" else r[1] for r in rows],
                      "total_mv": 1e11}).to_parquet(data / "snapshots" / day / "cross_section.parquet")
    market.invalidate()
    detail = pd.DataFrame([{"code": "300308", "reason": "光模块+CPO", "first_time": "09:25:00", "last_time": "09:25:00",
                            "order_volume": 1e6, "order_amount": 1.44e8, "source": "ths"}])
    down_detail = pd.DataFrame([{"code": "000001", "reason": None, "first_time": "10:01:02", "last_time": "14:50:00",
                                 "order_volume": 0.0, "order_amount": 0.0, "source": "ths"}])
    monkeypatch.setattr(market.limit_detail, "details", lambda day, side="up": (
        detail if side == "up" else down_detail) if day == "2026-11-13" else detail.iloc[:0])
    b = market.limit_board("2026-11-13")
    assert (b["limit_up"], b["limit_down"], b["broken"], b["max_streak"]) == (1, 1, 1, 2)
    assert b["broken_rate"] == pytest.approx(50.0)
    assert b["ladder"] == [{"streak": 2, "stocks": [{"code": "300308", "name": "中际旭创", "pct_chg": 20.0, "close": 144.0,
                                                     "amount": 1e9, "turnover": 1.0, "industry": "通信", "industry_l1": "通信",
                                                     "shape": "一字板", "reason": "光模块+CPO", "first_time": "09:25:00",
                                                     "last_time": "09:25:00", "order_volume": 1e6,
                                                     "order_amount": 1.44e8, "streak": 2}]}]
    assert b["detail_source"] == ["ths"]
    assert [x["code"] for x in b["broken_list"]] == ["600519"] and [x["code"] for x in b["down_list"]] == ["000001"]
    assert (b["down_list"][0]["first_time"], b["down_list"][0]["last_time"]) == ("10:01:02", "14:50:00")
    assert b["broken_list"][0]["industry"] == "白酒Ⅱ", "the level-2 industry where there is one"
    assert b["broken_list"][0]["industry_l1"] == "食品饮料"
    first = market.limit_board("2026-11-12")["ladder"][0]["stocks"][0]
    assert (first["streak"], first["shape"], first["reason"]) == (1, "换手板", None), "no details for a stock the pools lack"
    client = TestClient(create_app(RunManager(runner=lambda r, e: None), reports_root=tmp_path, watchlist_path=tmp_path / "w.json"))
    assert client.get("/api/market/limits?date=2026-11-13").json()["max_streak"] == 2
    market.invalidate()


def test_index_closes_come_from_the_local_series_and_start_the_day_before(mkt, monkeypatch):
    import pandas as pd

    from tradingagents.dataflows.vendors.akshare import store

    market, fake, data = mkt
    _history_store(data, monkeypatch, store, market)
    calls = []

    def daily(symbol, start_date):
        calls.append(symbol)
        return pd.DataFrame({"date": ["2026-11-06", "2026-11-12", "2026-11-13"], "close": [100.0, 101.0, 99.0]})
    fake.stock_zh_index_daily_em = daily
    market._INDEX_MEMO.clear()
    st = market.market_stats("2026-11-13", "1d")
    assert st["index_base"] == "2026-11-12" and st["index_error"] is None
    assert st["indexes"]["沪深300"] == [{"date": "2026-11-12", "close": 101.0}, {"date": "2026-11-13", "close": 99.0}]
    market.market_stats("2026-11-13", "60d")
    assert sorted(calls) == ["sh000001", "sh000300", "sh000680", "sh000852", "sh000905", "sz399006", "sz399102"], "once per index per day"
    market._INDEX_MEMO.clear()


@pytest.mark.parametrize("end, rng, start", [
    ("2026-08-31", "6m", "2026-02-28"), ("2026-11-17", "1y", "2025-11-17"), ("2026-03-15", "6m", "2025-09-15"),
    ("2026-11-17", "1d", "2026-11-17"),
])
def test_stats_ranges_count_back_by_calendar_months(end, rng, start):
    from web.server import market

    assert market._range_start(end, rng, [end]) == start


def test_closed_days_after_the_newest_snapshot_can_be_picked_and_are_synced(mkt, monkeypatch, tmp_path):
    import pandas as pd

    from tradingagents.dataflows.vendors.akshare import store
    from web.server.sync_job import SyncJob

    market, fake, data = mkt
    _history_store(data, monkeypatch, store, market)
    fake.stock_individual_fund_flow_rank = lambda indicator: pd.DataFrame({"代码": ["300308"], "今日主力净流入-净额": [1.0]})
    monkeypatch.setattr(store, "_CAL", pd.DatetimeIndex(pd.to_datetime(
        ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-12", "2026-11-13", "2026-11-16", "2026-11-17"])))
    monkeypatch.setattr(store, "last_closed_trade_date", lambda now=None: pd.Timestamp("2026-11-17").date())
    cal = market.calendar()
    assert cal["max"] == "2026-11-17" and cal["latest"] == "2026-11-13"
    assert cal["missing"] == ["2026-11-16", "2026-11-17"]

    def runner():                                   # what snapshots.update writes, minus the network
        for day in ("20261116", "20261117"):
            src = data / "snapshots" / "20261113" / "cross_section.parquet"
            (data / "snapshots" / day).mkdir()
            pd.read_parquet(src).assign(trade_date=pd.Timestamp(day)).to_parquet(data / "snapshots" / day / "cross_section.parquet")
        return {"status": "ok", "date": "20261117", "gap_days": 1}

    job = SyncJob(runner=runner, on_done=market.invalidate)
    client = TestClient(create_app(RunManager(runner=lambda r, e: None), reports_root=tmp_path,
                                   watchlist_path=tmp_path / "w.json", sync_job=job))
    assert client.get("/api/market?date=2026-11-13").status_code == 200, "cached before the sync"
    r = client.get("/api/market?date=2026-11-17")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "not_synced" and detail["missing"] == ["2026-11-16", "2026-11-17"]
    assert detail["sync"]["state"] == "idle"
    started = client.post("/api/market/sync").json()
    assert started["days"] == ["2026-11-16", "2026-11-17"]
    job.join(5)
    status = client.get("/api/market/sync").json()
    assert status["state"] == "ok" and "补了 1 个" in status["msg"]
    table = client.get("/api/market?date=2026-11-17").json()
    assert table["date"] == "2026-11-17" and table["dates"][:2] == ["2026-11-17", "2026-11-16"]
    assert client.get("/api/market/calendar").json()["missing"] == []
    assert client.post("/api/market/sync").json()["msg"] == "本地行情已是最新"


def test_a_failed_sync_reports_why(mkt):
    from web.server.sync_job import SyncJob

    job = SyncJob(runner=lambda: {"status": "incomplete", "msg": "120 只下载失败"})
    job.start(["2026-11-17"])
    job.join(5)
    assert job.status()["state"] == "error" and job.status()["msg"] == "120 只下载失败"
    boom = SyncJob(runner=lambda: _boom())
    boom.start(["2026-11-17"])
    boom.join(5)
    assert boom.status()["state"] == "error" and "rate limited" in boom.status()["msg"]


@pytest.mark.parametrize("day, period", [
    ("2026-11-13", "20260930"), ("2026-10-31", "20260930"), ("2026-10-30", "20260630"),
    ("2026-04-30", "20260331"), ("2026-04-29", "20250930"), ("2025-06-18", "20250331"),
])
def test_ttm_uses_the_period_every_company_had_published(day, period):
    from web.server import market

    assert market.period_for(day) == period


def test_rows_carry_their_exchange_and_the_csi_300_members(mkt):
    import pandas as pd

    market, fake, _ = mkt
    fake.stock_individual_fund_flow_rank = lambda indicator: pd.DataFrame({"代码": ["300308"], "今日主力净流入-净额": [1.0]})
    by = {r["code"]: r["exchange"] for r in market.market_table()["rows"]}
    assert by == {"300308": "SZ", "600519": "SH", "000001": "SZ", "002142": "SZ"}
    fake.index_stock_cons_csindex = lambda symbol: pd.DataFrame({"成分券代码": ["600519", "1"], "日期": "2026-11-11"})
    m = market.index_members("000300")
    assert m == {"index": "000300", "name": "沪深300", "as_of": "2026-11-11", "codes": ["600519", "000001"]}
    with pytest.raises(ValueError):
        market.index_members("399006")


def test_csi_300_members_fall_back_to_sina(mkt):
    import pandas as pd

    market, fake, _ = mkt
    fake.index_stock_cons_csindex = _boom
    fake.index_stock_cons = lambda symbol: pd.DataFrame({"品种代码": ["600519"], "品种名称": ["贵州茅台"]})
    m = market.index_members("000300")
    assert m["codes"] == ["600519"] and m["as_of"] is None


def test_limit_shapes():
    import pandas as pd

    from web.server import market

    rows = pd.DataFrame({"trade_date": "2026-11-17", "code": ["600001", "600002", "600003", "600004"],
                         "name": ["一字", "T字", "换手", "炸板"], "pre_close": 10.0,
                         "open": [11.0, 11.0, 10.2, 10.5], "low": [11.0, 10.6, 10.0, 10.3],
                         "high": 11.0, "close": [11.0, 11.0, 11.0, 10.8], "pct_chg": [10.0, 10.0, 10.0, 8.0],
                         "amount": 1e8, "turnover": 2.5})
    _, events = market._stats_of(rows)
    assert dict(zip(events["code"], events["shape"], strict=False)) == {
        "600001": "一字板", "600002": "T字板", "600003": "换手板", "600004": ""}


def test_limit_details_from_ths_pages_then_eastmoney(monkeypatch, tmp_path):
    import pandas as pd

    from web.server import limit_detail as L

    monkeypatch.setattr(L, "_cache", lambda day, side="up": tmp_path / f"{'' if side == 'up' else 'down_'}{day}.parquet")
    monkeypatch.setattr(L, "_failed", {})
    monkeypatch.setattr(L, "_PAGE", 1)
    pages = {1: {"code": "002983", "reason_type": "MicroLED+AI眼镜", "first_limit_up_time": "1794879342",
                 "last_limit_up_time": "1794898137", "order_volume": 1195188.0, "order_amount": 28624753.0},
             2: {"code": "600936", "reason_type": "AI应用", "first_limit_up_time": "1794879237",
                 "last_limit_up_time": "1794898098", "order_volume": 1379400.0, "order_amount": 6096948.0}}

    class R:
        def __init__(self, body): self.body = body
        def raise_for_status(self): pass
        def json(self): return self.body

    def get(url, params, **_):
        return R({"data": {"page": {"total": 2}, "info": [pages[params["page"]]]}})

    ths = L.fetch_ths("2026-11-17", get=get)
    assert ths["code"].tolist() == ["002983", "600936"]
    assert ths.iloc[0][["first_time", "last_time"]].tolist() == ["09:35:42", "14:48:57"], "unix time read in China time"
    em = pd.DataFrame({"code": ["002983", "920489"], "reason": None, "first_time": ["09:30:00", "11:01:35"],
                       "last_time": ["09:30:00", "14:38:17"], "order_volume": [1.0, 1242933.0],
                       "order_amount": [1.0, 15586379.0], "source": "em"})
    out = L.details("2026-11-13", ths=lambda d: ths, em=lambda d: em)
    assert out.set_index("code")["source"].to_dict() == {"002983": "ths", "600936": "ths", "920489": "em"}
    assert (tmp_path / "2026-11-13.parquet").exists(), "a closed day is kept"
    assert len(L.details("2026-11-13", ths=None, em=None)) == 3, "then read from disk"

    def down(d):
        raise ConnectionError("down")
    calls = []
    assert L.details("2026-11-12", ths=down, em=lambda d: calls.append(d) or down(d)).empty
    assert L.details("2026-11-12", ths=down, em=lambda d: calls.append(d) or down(d)).empty
    assert len(calls) == 1, "a day neither feed serves is not asked again at once"
    down = pd.DataFrame([{"code": "603721", "reason": None, "first_time": "14:52:10", "last_time": "14:54:43",
                          "order_volume": 0.0, "order_amount": 0.0, "source": "ths"}])
    got = L.details("2026-11-13", ths=lambda d: down, em=lambda d: down.iloc[:0], side="down")
    assert got["code"].tolist() == ["603721"], "the limit-down side has its own cache"
    assert (tmp_path / "down_2026-11-13.parquet").exists()

    seen = []

    def get_down(url, params, **_):
        seen.append(url)
        return R({"data": {"page": {"total": 1}, "info": [{"code": "603721", "first_limit_down_time": "1794897130",
                                                            "last_limit_down_time": "1794898483"}]}})
    d = L.fetch_ths("2026-11-17", get=get_down, side="down")
    assert seen[0].endswith("lower_limit_pool") and d.iloc[0][["first_time", "last_time"]].tolist() == ["14:32:10", "14:54:43"]
