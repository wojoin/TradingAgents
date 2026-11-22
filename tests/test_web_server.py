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

from web.server import settings, sw3, sw_class
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
    monkeypatch.setattr(sw3, "ensure", lambda: None)   # never a real 申万三级 download in tests
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


def test_a_deleted_report_goes_to_the_trash_and_leaves_the_list(env):
    client, _, root, _ = env
    rid = "300308.SZ_20261115_012528"
    write_report(root)
    r = client.delete(f"/api/reports/{rid}")
    assert r.status_code == 200 and r.json()["deleted"] == rid
    assert client.get("/api/reports").json() == [] and client.get(f"/api/reports/{rid}").status_code == 404
    assert (root / ".trash" / rid / "complete_report.md").is_file()          # kept: recoverable
    assert client.delete(f"/api/reports/{rid}").status_code == 404
    # The same report written and deleted again: the first copy in the trash is kept.
    write_report(root)
    client.delete(f"/api/reports/{rid}")
    assert len(list((root / ".trash").iterdir())) == 2
    for bad in ("..%2Freports", ".trash", "nope"):     # never resolved to a path: nothing removed
        assert client.delete(f"/api/reports/{bad}").status_code in (404, 405)
    assert (root / ".trash").is_dir() and len(list((root / ".trash").iterdir())) == 2


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


def test_sw3_builds_level_three_and_the_table_carries_it(mkt):
    import pandas as pd

    market, fake, data = mkt
    fake.stock_individual_fund_flow_rank = _boom
    fake.stock_fund_flow_individual = lambda symbol: pd.DataFrame()
    listing = pd.DataFrame({"行业代码": ["850111.SI", "857421.SI"], "行业名称": ["白酒Ⅲ", "通信网络设备及器件"],
                            "上级行业": ["白酒Ⅱ", "通信设备"]})
    cons = {"850111.SI": pd.DataFrame({"股票代码": ["600519.SH"]}),
            "857421.SI": pd.DataFrame({"股票代码": ["300308.SZ"]})}
    assert sw3.members().empty and sw3.status()["ready"] is False
    meta = sw3.build(lambda: listing, lambda c: cons[c], pause=0)
    assert meta["stocks"] == 2 and meta["failed"] == [] and (data / "web" / "sw3" / "members.parquet").exists()
    row = {r["code"]: r for r in market.market_table()["rows"]}
    assert row["600519"]["industry3"] == "白酒Ⅲ" and row["300308"]["industry3"] == "通信网络设备及器件"
    assert row["000001"]["industry3"] is None

    # A later build where one industry fails keeps that industry's stocks from the last build.
    def flaky(c):
        if c == "857421.SI":
            raise ConnectionError("down")
        return cons[c]
    path = data / "web" / "sw3" / "members.parquet"
    before = path.stat().st_mtime_ns
    meta = sw3.build(lambda: listing, flaky, pause=0)
    assert meta["failed"] == ["通信网络设备及器件"] and sw3.members().loc["300308", "sw3"] == "通信网络设备及器件"
    # Nothing changed: the file on disk is left as it was, and no change is recorded.
    assert path.stat().st_mtime_ns == before and meta["changes"] == []

    # A stock that moved and one that joined: the file is rewritten and the change recorded.
    cons["850111.SI"] = pd.DataFrame({"股票代码": ["600519.SH", "300308.SZ", "000001.SZ"]})
    cons["857421.SI"] = pd.DataFrame({"股票代码": []})
    meta = sw3.build(lambda: listing, lambda c: cons[c], pause=0)
    last = meta["changes"][0]
    assert (last["added"], last["removed"], last["moved"]) == (1, 0, 1)
    assert last["examples"]["moved"] == ["300308"] and sw3.members().loc["000001", "sw3"] == "白酒Ⅲ"
    assert sw3.status()["last_change"]["added"] == 1


def _sw_files(folder, rows):
    """申万's two files as pandas reads them (xlsx content under the .xls names is fine)."""
    import pandas as pd

    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"行业代码": ["340501", "730102", "480301"], "一级行业名称": ["食品饮料", "通信", "银行"],
                  "二级行业名称": ["白酒Ⅱ", "通信设备", "股份制银行Ⅱ"],
                  "三级行业名称": ["白酒Ⅲ", "通信网络设备及器件", "股份制银行Ⅲ"]}).to_excel(
        folder / "SwClassCode_2021.xls", index=False, engine="openpyxl")
    pd.DataFrame(rows, columns=["股票代码", "计入日期", "行业代码", "更新日期"]).to_excel(
        folder / "StockClassifyUse_stock.xls", index=False, engine="openpyxl")
    return folder


def test_sw_class_files_give_all_three_levels_and_lg_fills_the_rest(mkt, tmp_path, monkeypatch):
    import pandas as pd

    market, fake, data = mkt
    fake.stock_individual_fund_flow_rank = _boom
    fake.stock_fund_flow_individual = lambda symbol: pd.DataFrame()
    downloads = tmp_path / "Downloads"
    monkeypatch.setattr(sw_class, "downloads_dir", lambda: downloads)
    # 乐咕乐股 has 000001 only: the fallback, used where 申万's files have nothing.
    sw3.build(lambda: pd.DataFrame({"a": ["857831.SI"], "b": ["股份制银行Ⅲ"], "c": ["股份制银行Ⅱ"]}),
              lambda c: pd.DataFrame({"股票代码": ["000001.SZ"]}), pause=0)
    assert sw_class.import_downloads()["found"] is False
    # The browser saved both: 600519 moved from 通信 to 白酒 in 2021 (the latest entry counts).
    _sw_files(downloads, [["600519", "2001-08-27", "730102", "2015-10-27"],
                          ["600519", "2021-07-30", "340501", "2021-07-31"],
                          ["300308", "2012-04-10", "730102", "2026-11-20"]] * 40)
    out = sw_class.import_downloads()
    assert out["found"] and out["changed"] and out["as_of"] == "2026-11-20"
    market.industries.cache_clear()
    rows = {r["code"]: r for r in market.market_table()["rows"]}
    assert (rows["600519"]["industry"], rows["600519"]["sub_industry"], rows["600519"]["industry3"]) == ("食品饮料", "白酒Ⅱ", "白酒Ⅲ")
    assert rows["300308"]["industry3"] == "通信网络设备及器件" and "industry3_src" not in rows["300308"]
    assert rows["000001"]["industry3"] == "股份制银行Ⅲ" and rows["000001"]["industry3_src"] == "lg"
    assert sw_class.status()["ready"] and sw_class.status()["due"] is False

    # The same file downloaded again: not copied, nothing recorded.
    kept = (data / "manual" / "sw_class" / "StockClassifyUse_stock.xls").stat().st_mtime_ns
    again = sw_class.import_downloads()
    assert again["changed"] is False and (data / "manual" / "sw_class" / "StockClassifyUse_stock.xls").stat().st_mtime_ns == kept
    # A newer one in which 000001 joins and 300308 moves: copied, and the change recorded.
    _sw_files(downloads, [["600519", "2021-07-30", "340501", "2021-07-31"],
                          ["300308", "2026-12-01", "480301", "2026-12-01"],
                          ["000001", "2021-07-30", "480301", "2026-12-01"]] * 40)
    out = sw_class.import_downloads()
    assert out["changed"] and (out["diff"]["added"], out["diff"]["removed"], out["diff"]["moved"]) == (1, 0, 1)
    assert sw_class.status()["last_change"]["examples"]["moved"] == ["300308"]


def test_the_sw_class_import_endpoint_looks_only_at_files_after_since(env, tmp_path, monkeypatch):
    downloads = tmp_path / "Downloads"
    monkeypatch.setattr(sw_class, "downloads_dir", lambda: downloads)
    monkeypatch.setattr(sw_class, "_dir", lambda: tmp_path / "kept")
    _sw_files(downloads, [["600519", "2021-07-30", "340501", "2021-07-31"]] * 200)
    client = env[0]
    late = (downloads / "StockClassifyUse_stock.xls").stat().st_mtime + 60
    assert client.post(f"/api/market/sw-class/import?since={late}").json()["found"] is False
    r = client.post("/api/market/sw-class/import?since=0").json()
    assert r["found"] and r["changed"] and r["status"]["ready"]


def test_without_eastmoney_the_flow_is_ths_and_labelled_so(mkt):
    import pandas as pd

    market, fake, _ = mkt
    fake.stock_individual_fund_flow_rank = _boom
    # Fetched page by page while prices move, 同花顺's ranking can list a stock twice: the first kept.
    fake.stock_fund_flow_individual = lambda symbol: pd.DataFrame({"股票代码": ["300308", "300308"], "净额": ["-5.33亿", "-5.30亿"]})
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
                                "median": 10.0, "limit_up": 0, "limit_down": 0, "broken": 0,
                                "amount_r5": None, "amount_r20": None}, "放量 / 缩量 needs 5 (20) days before"
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
    assert sorted(calls) == ["sh000001", "sh000300", "sh000680", "sh000688", "sh000852", "sh000905", "sz399006", "sz399102"], "once per index per day"
    market._INDEX_MEMO.clear()


def test_index_closes_fall_back_to_sina_when_eastmoney_fails(monkeypatch):
    import pandas as pd

    from web.server import market

    class Fake:
        def stock_zh_index_daily_em(self, symbol, start_date):
            raise ConnectionError("Push2RateLimitError")

        def stock_zh_index_daily(self, symbol):
            return pd.DataFrame({"date": ["2026-11-05", "2026-11-12", "2026-11-13"], "close": [1.0, 2.0, 3.0]})
    monkeypatch.setattr(market.store, "ak", lambda: Fake())
    got = market._index_daily("sh000688", "20261110")
    assert got["close"].tolist() == [2.0, 3.0], "Sina's whole history, cut at the start"


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


def test_breadth_counts_new_highs_moving_averages_size_bands_and_limit_follow_through(monkeypatch, tmp_path):
    import pandas as pd

    from web.server import breadth, market

    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-01-05", periods=65)]
    base_days, last = days[:-1], days[-1]
    # A rises 1% a day, B falls 1% a day, C stays put; D is an ST stock (left out of the size bands).
    moves = {"600001": 1.0, "600002": -1.0, "600003": 0.0, "600004": 0.5}
    names = {"600001": "甲", "600002": "乙", "600003": "丙", "600004": "*ST丁"}
    panel, close = [], dict.fromkeys(moves, 10.0)
    for d in base_days:
        for c, m in moves.items():
            close[c] *= 1 + m / 100
            panel.append({"date": d, "code": c, "name": names[c], "pct_chg": m, "close": close[c], "amount": 1e8,
                          "volume": {"600001": 3e5, "600002": 1e5, "600003": 1e5, "600004": 1e5}[c]})
    xs = pd.DataFrame({"code": list(moves), "name": list(names.values()), "pct_chg": list(moves.values()),
                       "close": [close[c] * (1 + m / 100) for c, m in moves.items()],
                       "float_mv": [300.0, 200.0, 100.0, 1000.0], "amount": 1e8, "volume": [3e5, 1e5, 1e5, 1e5]})
    # Limit-ups: A on the last four days (a run), B the day before the last.
    events = pd.DataFrame([{"date": d, "code": "600001", "kind": "up"} for d in days[-4:]]
                          + [{"date": days[-2], "code": "600002", "kind": "up"}])
    monkeypatch.setattr(breadth, "_base_panel", lambda: pd.DataFrame(panel))
    monkeypatch.setattr(market, "base_through_day", lambda: base_days[-1])
    monkeypatch.setattr(market, "available_dates", lambda: [last])
    monkeypatch.setattr(market, "_read_xs", lambda day: xs)
    stats = pd.DataFrame({"date": days, "up": 3, "down": 1, "limit_up": 1, "limit_down": 0, "broken": 1})
    monkeypatch.setattr(market, "_span_stats", lambda span: (stats, events))
    monkeypatch.setattr(market, "_days_on_record", lambda end: days)
    monkeypatch.setattr(breadth, "MIN_STOCKS", 1)
    monkeypatch.setattr(breadth, "MIN_BAND", 1)
    monkeypatch.setattr(breadth, "MIN_BOARD", 1)
    monkeypatch.setattr(breadth, "SIZE_BANDS", (("大盘", 0, 1), ("微盘", -1, None)))
    monkeypatch.setattr(breadth, "BAND_RULES", {"大盘": "最大 1 只", "微盘": "最小 1 只"})
    breadth.invalidate()

    b = breadth.breadth(None, "60d")
    day = b["days"][-1]
    assert b["end"] == last and len(b["days"]) == 60
    assert (day["nh60"], day["nl60"]) == (2, 1), "A and the ST stock make 60-day highs, B a low; C neither"
    assert day["nh250"] is None, "not enough history for 250 days"
    assert day["ma20"] == pytest.approx(50.0) and day["ma60"] == pytest.approx(50.0), "A and D above, B and C not"
    # By float value without the ST stock: A is the largest, C the smallest.
    assert (day["size_大盘"], day["size_微盘"]) == (1.0, 0.0)
    # Yesterday A (3 in a row) and B (首板) closed at the limit; today A does again, B does not.
    assert (day["prem_n"], day["prem_avg"], day["prem_up"]) == (2, 0.0, 50.0)
    assert (day["promo_1"], day["promo_3"], day["promo_multi"], day["promo_all"]) == (0.0, 100.0, 100.0, 50.0)
    assert day["promo_2"] is None, "no 2-in-a-row stock yesterday"
    assert b["days"][0]["prem_n"] == 0, "no limit-up the day before"
    assert (day["height"], day["multi_n"]) == (4, 1), "A on its fourth limit-up in a row"
    assert day["board_主板"] == pytest.approx(0.25), "all four are 主板: the median of 1, -1, 0, 0.5"
    assert day["board_创业板"] is None and day["conc100"] is None, "too few stocks for these"
    assert day["trin_amt"] is None and day["mcl_osc"] is None, "TRIN and McClellan need a whole market"
    monkeypatch.setattr(breadth, "MIN_MARKET", 1)
    breadth.invalidate()
    day = breadth.breadth(None, "60d")["days"][-1]
    # Two rise (A, D) and one falls (B), each 1亿 traded: TRIN_额 (2/1)/(2亿/1亿) = 1;
    # by volume A trades 3x: (2/1)/(4/1) = 0.5.
    assert (day["trin_amt"], day["trin_vol"]) == (1.0, 0.5) and (day["trin_amt10"], day["trin_vol10"]) == (1.0, 0.5)
    # Every day (2 - 1) / 3 * 1000: a flat ratio, so the two EMAs agree and the oscillator is 0.
    assert day["mcl_ratio"] == pytest.approx(333.333, abs=0.01) and day["mcl_osc"] == 0
    assert day["mcl_sum"] == pytest.approx(3333.33, abs=0.1), "MSI: 10 x a steady net advance ratio"
    assert day["conc100"] == 100.0, "fewer than 100 stocks: all of it"
    # 2 rise and 1 falls every day: ADR 2, ABI 1/3, a flat thrust at 2/3 that never fired.
    assert (day["adr"], day["adr10"], day["abi"], day["thrust"]) == (2.0, 2.0, 33.333, 0.667)
    assert day["thrust_signal"] is False and day["ma250"] is None, "not 250 days of history"
    assert (day["ud_amt"], day["ud_vol"]) == (2.0, 4.0), "rising stocks' amount 2亿 vs 1亿; volume 4 vs 1"
    # 涨家占比 2/4; the amount evenly spread, so 涨额占比 is the same (额价差 0); by volume the
    # rising pair trade 4 of 6 (量价差 +16.67). 60-day: 2 highs, 1 low of 4 stocks.
    assert (day["up_pct"], day["up_amt_pct"], day["amt_gap"]) == (50.0, 50.0, 0.0)
    assert (day["up_vol_pct"], day["vol_gap"]) == (66.667, 16.667)
    assert day["net60_pct"] == 25.0 and day["mcl_raw"] == 0, "a steady net count: the raw oscillator at 0 too"
    # 情绪综合分: 涨跌比 75, 涨停跌停比 100, 封板率 50, 溢价 0% -> 50, 晋级率 50% -> 100 (capped), 4 板 -> 3/7.
    parts = {k: day[f"m_{k}"] for k in ("updown", "limit", "seal", "prem", "promo", "height")}
    assert parts == pytest.approx({"updown": 75, "limit": 100, "seal": 50, "prem": 50, "promo": 100, "height": 300 / 7}, abs=0.01)
    assert day["mood"] == pytest.approx(sum(parts.values()) / 6, abs=0.01)
    with pytest.raises(ValueError):
        breadth.breadth(None, "2y")
    client = TestClient(create_app(RunManager(runner=lambda r, e: None), reports_root=tmp_path, watchlist_path=tmp_path / "w.json"))
    assert client.get("/api/market/breadth?range=60d").json()["days"][-1]["nh60"] == 2
    assert client.get("/api/market/breadth?range=bad").status_code == 400
    breadth.invalidate()


def test_sectors_heat_map_valuation_ranks_and_the_market_series(monkeypatch, tmp_path):
    import pandas as pd

    from web.server import market, sectors

    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-10-01", periods=25)]
    rows = []
    for i, d in enumerate(days):
        # 银行 rises 1% a day, its PE climbing (today the highest); 电子 falls 1%, PE falling.
        rows.append({"指数代码": "801780", "指数名称": "银行", "发布日期": d, "涨跌幅": 1.0, "市盈率": 5 + i * 0.1,
                     "市净率": 0.5, "股息率": 4.5, "成交额占比": 3.0})
        rows.append({"指数代码": "801080", "指数名称": "电子", "发布日期": d, "涨跌幅": -1.0, "市盈率": 60 - i,
                     "市净率": 5.0, "股息率": 0.5, "成交额占比": 12.0})
    rows.append({"指数代码": "801230", "指数名称": "综合", "发布日期": days[0], "涨跌幅": 0.0, "市盈率": 1,
                 "市净率": 1, "股息率": 1, "成交额占比": 0.1})            # gone from today's classification
    mkt = pd.DataFrame({"日期": days, "市盈率": [15.0 + i * 0.1 for i in range(25)], "市净率": 1.7, "股息率": 1.9})
    fetched = []

    def fetch(name):
        fetched.append(name)
        return pd.DataFrame(rows) if name == "sw_daily" else mkt
    monkeypatch.setattr(sectors, "_fetch", fetch)
    monkeypatch.setattr(market, "last_closed_day", lambda: days[-1])
    from web.server import extras
    # The bond yield is published for every other day only: each day takes the last one before it.
    monkeypatch.setattr(extras, "_fetch_bond", lambda: pd.DataFrame({"日期": days[::2], "中国国债收益率10年": 2.0}))
    extras.invalidate()
    sectors.invalidate()

    r = sectors.sectors(None, 20)
    assert r["as_of"] == days[-1] and r["dates"] == days[-20:]
    assert [x["name"] for x in r["industries"]] == ["银行", "电子"], "by the change over the window; 综合 left out"
    bank = r["industries"][0]
    assert bank["cum"] == pytest.approx((1.01 ** 20 - 1) * 100, abs=0.01)
    assert bank["cum5"] == pytest.approx((1.01 ** 5 - 1) * 100, abs=0.01)
    assert len(bank["pct"]) == 20 and bank["pe_rank"] == 100.0 and r["industries"][1]["pe_rank"] == pytest.approx(4.0)
    assert sectors.sectors(days[9], 10)["dates"] == days[:10]
    # 二级: its own series, each named after its 一级 (from the 申万 code).
    rows2 = [{"指数代码": "801783", "指数名称": "股份制银行Ⅱ", "发布日期": d, "涨跌幅": 0.5, "市盈率": 5.0,
              "市净率": 0.5, "股息率": 5.0, "成交额占比": 1.0} for d in days]
    monkeypatch.setattr(sectors, "_fetch", lambda name: pd.DataFrame(rows2) if name == "sw_daily2" else fetch(name))
    sectors.invalidate()
    two = sectors.sectors(None, 10, "sw2")
    assert two["level"] == "sw2" and [(x["name"], x["sw1"]) for x in two["industries"]] == [("银行-股份制银行Ⅱ", "银行")]
    with pytest.raises(ValueError):
        sectors.sectors(None, 10, "sw3")
    fetched.clear()
    with pytest.raises(ValueError):
        sectors.sectors(None, 30)

    v = sectors.valuation(days[4])
    assert v["as_of"] == days[4] and [d["pe"] for d in v["days"]] == [15.0, 15.1, 15.2, 15.3, 15.4]
    assert v["days"][1]["y10"] == 2.0 and v["days"][0]["erp"] == pytest.approx(100 / 15 - 2, abs=1e-3), "股债性价比"
    assert fetched == ["sw_market"], "once per series per closed day"

    client = TestClient(create_app(RunManager(runner=lambda r, e: None), reports_root=tmp_path, watchlist_path=tmp_path / "w.json"))
    assert client.get("/api/market/sectors?days=10").json()["industries"][0]["name"] == "银行"
    assert client.get("/api/market/sectors?days=7").status_code == 400
    assert len(client.get("/api/market/valuation").json()["days"]) == 25
    sectors.invalidate()
    extras.invalidate()


def test_sectors_fall_back_to_the_disk_copy(monkeypatch, tmp_path):
    import pandas as pd

    from tradingagents.dataflows.vendors.akshare import store
    from web.server import market, sectors

    def down(name):
        raise ConnectionError("申万 down")
    monkeypatch.setattr(sectors, "_fetch", down)
    monkeypatch.setattr(market, "last_closed_day", lambda: "2026-11-17")
    sectors.invalidate()
    monkeypatch.setattr(store, "ts_path", lambda name: __import__("pathlib").Path("/nonexistent") / f"{name}.parquet")
    with pytest.raises(LookupError):
        sectors.valuation()
    sectors.invalidate()

    from web.server import extras
    monkeypatch.setattr(extras, "_fetch_bond", lambda: pd.DataFrame({"日期": ["2026-11-13"], "中国国债收益率10年": [1.6]}))
    extras.invalidate()
    # With a copy on disk: that copy, and a note saying so.
    monkeypatch.setattr(store, "ts_path", lambda name: tmp_path / f"{name}.parquet")
    pd.DataFrame({"日期": ["2026-11-13"], "市盈率": [15.9], "市净率": [1.78], "股息率": [1.8]}).to_parquet(tmp_path / "sw_market.parquet")
    v = sectors.valuation()
    assert v["days"][-1]["pe"] == 15.9 and "使用本地数据" in v["note"]
    sectors.invalidate()



def test_margin_joins_the_exchanges_and_tops_up_the_history(monkeypatch, tmp_path):
    import pandas as pd

    from web.server import extras, market

    days = ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-16"]
    monkeypatch.setattr(market, "last_closed_day", lambda: days[-1])
    monkeypatch.setattr(market, "trading_days", lambda: days)

    def hist(ex):     # the long history ends on 11-11
        v = 100.0 if ex == "margin_sh" else 50.0
        return pd.DataFrame({"date": days[:2], "total": [v, v + 1], "fin": [v - 1, v], "fin_buy": [1.0, 1.0]})
    asked = []

    def sse(start, end):
        asked.append(("sse", start, end))
        return pd.DataFrame({"date": days[2:], "total": [102.0, 103.0, 104.0], "fin": 1.0, "fin_buy": 1.0})

    def szse(day):
        asked.append(("szse", day))
        if day == days[-1]:              # not published yet
            return pd.DataFrame(columns=extras._MARGIN_COLS)
        return pd.DataFrame([{"date": day, "total": 60.0, "fin": 1.0, "fin_buy": 1.0}])
    extras.invalidate()
    m = extras.margin(None, "60d", build=lambda: extras._build_margin(hist, sse, szse))
    assert ("sse", "2026-11-12", "2026-11-16") in asked and ("szse", "2026-11-16") in asked
    assert m["as_of"] == "2026-11-13", "a day both exchanges have published"
    assert [d["total"] for d in m["days"]] == [150, 152, 162, 163]
    assert m["days"][-1]["chg"] == 1 and m["days"][0]["chg"] is None
    with pytest.raises(ValueError):
        extras.margin(None, "5y")
    extras.invalidate()


def test_margin_rates_show_whether_leverage_is_speeding_up(monkeypatch):
    import pandas as pd

    from web.server import extras

    # +2亿 a day for 30 days, then +4亿 a day for 5: the pace is picking up.
    tot = [2e12 + 2e8 * i for i in range(30)] + [2e12 + 58e8 + 4e8 * i for i in range(1, 6)]
    dates = [str(d.date()) for d in pd.bdate_range("2026-06-01", periods=len(tot))]
    df = pd.DataFrame({"date": dates, "total": tot, "fin": tot, "fin_buy": 1.0, "sh": tot, "sz": 0.0})
    extras.invalidate()
    m = extras.margin(None, "60d", build=lambda: (df, None))
    first, steady, last = m["days"][0], m["days"][29], m["days"][-1]
    assert first["chg5"] is None and first["s5"] is None and first["trend"] is None, "too early for a 5-day rate"
    assert steady["chg5"] == 10e8 and steady["chg20"] == 40e8
    assert steady["s5"] == 2e8 and steady["s20"] == 2e8 and steady["trend"] == "加杠杆放缓"
    assert last["chg5"] == 20e8 and last["s5"] == 4e8 and last["s20"] > 2e8 and last["trend"] == "加杠杆加快"
    # A later range still reads the days before its start for its first rates.
    m = extras.margin(None, "1d", build=lambda: (df, None))
    assert m["days"] == [last]
    extras.invalidate()


def test_themes_count_the_limit_up_reasons_by_day(monkeypatch):
    import pandas as pd

    from web.server import extras, market

    days = ["2026-11-12", "2026-11-13", "2026-11-16", "2026-11-17"]
    monkeypatch.setattr(market, "_days_on_record", lambda end: days)
    monkeypatch.setattr(market, "_names", lambda: pd.DataFrame({"code": ["000001", "000002", "000003"],
                                                                 "name": ["甲", "乙", "丙"]}))
    reasons = {
        "2026-11-13": {"000001": "AI应用+国资"},
        "2026-11-16": {"000001": "AI应用+国资", "000002": "商业航天"},
        "2026-11-17": {"000001": "AI应用+国资", "000002": "商业航天＋AI应用", "000003": None},
    }

    def details(d):
        r = reasons.get(d)
        return None if r is None else pd.DataFrame({"code": list(r), "reason": list(r.values())})
    t = extras.themes("2026-11-17", 3, details=details)
    assert t["dates"] == days[-3:] and t["have"] == days[-3:]
    top = t["themes"][0]
    assert (top["name"], top["today"], top["counts"], top["days_on"]) == ("AI应用", 2, [1, 1, 2], 3)
    assert [x["name"] for x in t["themes"]] == ["AI应用", "国资", "商业航天"], "today's count, then over the span"
    assert [s["name"] for s in top["stocks"]] == ["甲", "乙"]
    assert extras.split_reason("A＋B+ C") == ["A", "B", "C"] and extras.split_reason(None) == []
    with pytest.raises(ValueError):
        extras.themes(None, 7, details=details)



def test_qvix_and_the_market_flow(monkeypatch):
    import pandas as pd

    from web.server import extras, market

    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-08-03", periods=80)]
    monkeypatch.setattr(market, "last_closed_day", lambda: days[-1])
    monkeypatch.setattr(extras.store, "cached", lambda name, fn, policy="daily", refresh=False: fn())
    extras.invalidate()
    q = extras.qvix(None, "60d", fetch=lambda: pd.DataFrame({"date": days, "close": [10.0 + i % 20 for i in range(80)],
                                                              "high": 30.0}))
    assert q["as_of"] == days[-1] and len(q["days"]) == 60 and q["since"] == days[0]
    assert q["rank"] == pytest.approx(100.0), "the last close (29) is the highest so far"
    f = extras.market_flow(None, "60d", fetch=lambda: pd.DataFrame({
        "日期": days, "主力净流入-净额": -1e9, "超大单净流入-净额": -4e8, "大单净流入-净额": -6e8,
        "中单净流入-净额": 2e8, "小单净流入-净额": 8e8, "主力净流入-净占比": -1.5}))
    assert len(f["days"]) == 60 and f["days"][-1] == {"date": days[-1], "main": -1e9, "super": -4e8, "large": -6e8,
                                                        "mid": 2e8, "small": 8e8, "main_pct": -1.5}
    with pytest.raises(ValueError):
        extras.qvix(None, "9y")
    extras.invalidate()


def test_industry_flow_sums_by_shenwan_industry(monkeypatch):
    import pandas as pd

    from web.server import extras, market

    monkeypatch.setattr(market, "_days_on_record", lambda end: ["2026-11-17"])
    monkeypatch.setattr(market, "last_closed_day", lambda: "2026-11-17")
    monkeypatch.setattr(market, "industries", lambda: pd.DataFrame(
        {"sw1": ["电子", "电子", "银行"], "sw2": ["半导体", "消费电子", "股份制银行Ⅱ"]}, index=["000001", "000002", "000003"]))
    flows = pd.Series([3e8, -1e8, -5e8, 7e8], index=["000001", "000002", "000003", "999999"])
    got = extras.industry_flow(None, "5d", stock_flow=lambda day, span: flows)
    assert got["available"] and got["total"] == 4e8
    assert got["sw1"] == [{"name": "电子", "flow": 2e8}, {"name": "银行", "flow": -5e8}], "a stock without an industry left out"
    assert got["sw2"][0] == {"name": "电子-半导体", "flow": 3e8}
    none = extras.industry_flow(None, "10d", stock_flow=lambda day, span: None)
    assert not none["available"] and "都暂不可用" in none["note"], "the latest day: both feeds failed"
    monkeypatch.setattr(market, "last_closed_day", lambda: "2026-11-18")
    old = extras.industry_flow(None, "10d", stock_flow=lambda day, span: None)
    assert "只有最近一个交易日" in old["note"], "an earlier day: never to be had"
    with pytest.raises(ValueError):
        extras.industry_flow(None, "3d", stock_flow=lambda day, span: flows)
    ths = extras.industry_flow(None, "5d", stock_flow=lambda day, span: (flows, "ths"))
    assert ths["source"] == "ths" and "同花顺口径" in ths["source_note"] and ths["label"] == "资金净流入（同花顺）"
    assert got["source"] == "eastmoney" and got["source_note"] is None


def test_stock_flow_falls_back_to_tonghuashun(monkeypatch):
    import datetime as dt

    import pandas as pd

    from web.server import extras

    monkeypatch.setattr(extras.store, "last_closed_trade_date", lambda: dt.date(2026, 11, 18))
    em = pd.Series([1.0], index=["000001"])
    ths = pd.Series([2.0], index=["000001"])
    monkeypatch.setattr(extras, "_em_flow", lambda day, span: em)
    monkeypatch.setattr(extras, "_ths_flow", lambda day, span: ths)
    assert extras._stock_flow("2026-11-18", "5d")[1] == "eastmoney"
    monkeypatch.setattr(extras, "_em_flow", lambda day, span: None)        # Eastmoney rate-limited
    flow, source = extras._stock_flow("2026-11-18", "10d")
    assert source == "ths" and flow.iat[0] == 2.0
    assert extras._stock_flow("2026-11-17", "5d") == (None, None), "an earlier day: neither keeps it"
    monkeypatch.setattr(extras, "_ths_flow", lambda day, span: None)
    assert extras._stock_flow("2026-11-18", "5d") == (None, None)


def test_releases_and_the_lhb(monkeypatch, tmp_path):
    import pandas as pd

    from web.server import extras, market

    monkeypatch.setattr(market, "last_closed_day", lambda: "2026-11-17")
    monkeypatch.setattr(market, "_days_on_record", lambda end: ["2026-11-17"])
    extras.invalidate()
    summary = pd.DataFrame({"解禁时间": ["2026-11-18", "2026-11-20"], "当日解禁股票家数": [2, 1], "实际解禁市值": [3e9, 1e9]})
    detail = pd.DataFrame({"股票代码": ["688653", "601328"], "股票简称": ["康希通信", "交通银行"],
                           "解禁时间": ["2026-11-18", "2026-11-20"], "限售股类型": ["首发原股东限售股份", "其他类型"],
                           "实际解禁市值": [1e9, 2e9], "占解禁前流通市值比例": [0.25, 0.5]})
    r = extras.releases("2026-11-17", summary=lambda a, b: summary, detail=lambda a, b: detail)
    assert (r["end"], r["count"], r["total"]) == ("2026-12-17", 3, 4e9)
    assert [x["name"] for x in r["stocks"]] == ["交通银行", "康希通信"] and r["stocks"][0]["float_share"] == 50.0

    monkeypatch.setattr(extras, "_lhb_path", lambda day: tmp_path / f"{day}.parquet")
    monkeypatch.setattr(extras.store, "is_intraday", lambda: False)     # after the close: kept on disk
    # A convertible bond (no 解读) is on the list too, and left out.
    d = pd.DataFrame({"代码": ["000521", "000521", "000011", "113001"], "名称": ["长虹美菱", "长虹美菱", "深物业A", "某某转债"],
                      "收盘价": [4.74, 4.74, 6.94, 130.0], "涨跌幅": [9.98, 9.98, -9.64, 20.0],
                      "龙虎榜净买额": [8.6e7, 8.6e7, 3.1e7, 9e9], "龙虎榜买入额": [1.2e8, 1.2e8, 1.1e8, 1e10],
                      "龙虎榜卖出额": [3.9e7, 3.9e7, 8.2e7, 1e9], "净买额占总成交比": [24.0, 24.0, 4.1, 50.0],
                      "换手率": [5.7, 5.7, 9.5, 300.0], "解读": ["普通席位买入", "普通席位买入", None, None],
                      "上榜原因": ["日涨幅偏离值达7%", "连续三日涨幅偏离20%", "连续三日跌幅偏离20%", "转债异动"]})
    j = pd.DataFrame({"代码": ["000011"], "买方机构数": [0], "卖方机构数": [1], "机构买入净额": [-5e7]})
    monkeypatch.setattr(market, "cross_section", lambda day: (day, pd.DataFrame(
        {"code": ["000521", "000011"], "amount": [3.6e8, 7.5e8], "volume": [7.6e5, 1.08e6]})))
    lb = extras.lhb(None, detail=lambda k: d, inst=lambda k: j)
    assert (lb["stocks"][0]["amount"], lb["stocks"][0]["volume"]) == (3.6e8, 7.6e5), "from the day's snapshot"
    assert lb["count"] == 2 and [x["code"] for x in lb["stocks"]] == ["000521", "000011"], "one row a stock, by net buying"
    assert lb["stocks"][0]["reason"] == "日涨幅偏离值达7%；连续三日涨幅偏离20%"
    assert (lb["inst_net"], lb["inst_count"]) == (-5e7, 1) and lb["stocks"][0]["inst_net"] is None
    assert lb["stocks"][1]["note"] == "", "no 解读: empty, not NaN (which JSON cannot carry)"
    assert extras.lhb(None, detail=None, inst=None)["count"] == 2, "a closed day read back from disk"
    (tmp_path / "2026-11-17.parquet").unlink()
    assert not extras.lhb(None, detail=lambda k: pd.DataFrame(), inst=None)["available"], "not published yet"
    extras.invalidate()


def test_the_new_market_endpoints_pass_their_day_through(monkeypatch, tmp_path):
    # A Query shared between parameters serves only the first name: each must get its own.
    from web.server import extras

    for name in ("lhb", "releases"):
        monkeypatch.setattr(extras, name, lambda date=None: {"got": date})
    monkeypatch.setattr(extras, "industry_flow", lambda date=None, span="1d": {"got": date})
    for name in ("qvix", "market_flow", "margin"):
        monkeypatch.setattr(extras, name, lambda end=None, rng="1y": {"got": end})
    client = TestClient(create_app(RunManager(runner=lambda r, e: None), reports_root=tmp_path, watchlist_path=tmp_path / "w.json"))
    for url in ("lhb?date=", "releases?date=", "flow/industry?span=5d&date=", "qvix?end=", "flow?end=", "margin?end="):
        assert client.get(f"/api/market/{url}2026-11-13").json() == {"got": "2026-11-13"}, url
    assert client.get("/api/market/lhb?date=11-13").status_code == 422


def test_industry_crowding_ranks_turnover_share_and_rate_against_their_history(monkeypatch, tmp_path):
    import pandas as pd

    from web.server import market, sectors

    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-09-01", periods=40)]
    rows = []
    for i, d in enumerate(days):
        # 传媒's share and turnover climb to their highest; 银行's sink to their lowest.
        rows.append({"指数代码": "801760", "指数名称": "传媒", "发布日期": d, "涨跌幅": 1.0,
                     "成交额占比": 1 + i * 0.1, "换手率": 2 + i * 0.1})
        rows.append({"指数代码": "801780", "指数名称": "银行", "发布日期": d, "涨跌幅": -1.0,
                     "成交额占比": 5 - i * 0.1, "换手率": 3 - i * 0.05})
    monkeypatch.setattr(sectors, "_fetch", lambda name: pd.DataFrame(rows))
    monkeypatch.setattr(market, "last_closed_day", lambda: days[-1])
    sectors.invalidate()
    c = sectors.crowding(None)
    assert c["as_of"] == days[-1] and [x["name"] for x in c["industries"]] == ["传媒", "银行"]
    media, bank = c["industries"]
    assert (media["share_rank"], media["turnover_rank"], media["crowd"]) == (100.0, 100.0, 100.0)
    assert bank["crowd"] == pytest.approx(100 / 36, abs=0.1), "the lowest of 36 five-day averages"
    assert media["share5"] == pytest.approx(sum(1 + i * 0.1 for i in range(35, 40)) / 5, abs=0.01)
    assert media["share5_20d"] == pytest.approx(sum(1 + i * 0.1 for i in range(15, 20)) / 5, abs=0.01)
    assert media["cum20"] == pytest.approx((1.01 ** 20 - 1) * 100, abs=0.01)
    assert sectors.crowding(days[20])["as_of"] == days[20]
    client = TestClient(create_app(RunManager(runner=lambda r, e: None), reports_root=tmp_path, watchlist_path=tmp_path / "w.json"))
    assert client.get(f"/api/market/crowding?end={days[-1]}").json()["industries"][0]["name"] == "传媒"
    sectors.invalidate()


def test_the_daily_download_fetches_the_last_closed_day(monkeypatch):
    from web.server import daily, market

    monkeypatch.setattr(market, "last_closed_day", lambda: "2026-11-18")
    monkeypatch.setattr(daily, "_setup_logging", lambda: None)
    monkeypatch.setattr(daily, "server_up", lambda server: False)
    runs = []
    monkeypatch.setattr(daily, "in_process", lambda day: runs.append(day) or (0, 1))
    assert daily.main([]) == 1 and runs == ["2026-11-18"], "something not out yet: says so"
    monkeypatch.setattr(daily, "in_process", lambda day: runs.append(day) or (0, 0))
    assert daily.main([]) == 0 and runs == ["2026-11-18"] * 2, "run again: fetches again"
    monkeypatch.setattr(daily, "server_up", lambda server: True)
    monkeypatch.setattr(daily, "via_server", lambda server, day: runs.append(("server", day)) or (0, 0))
    assert daily.main([]) == 0 and runs[-1] == ("server", "2026-11-18"), "through the web server when it is up"


def test_lhb_seats_merge_both_sides_and_count_each_institution_once(monkeypatch, tmp_path):
    import pandas as pd

    from web.server import extras, market

    monkeypatch.setattr(market, "_days_on_record", lambda end: ["2026-11-17"])
    cols = ["交易营业部名称", "买入金额", "买入金额-占总成交比例", "卖出金额", "卖出金额-占总成交比例", "类型"]
    why = "日涨幅偏离值达到7%"
    # 沪股通 is among both the buyers and the sellers, each list giving only its own side;
    # two different institutions go by the one name 机构专用, one of them in both lists.
    buy = pd.DataFrame([["沪股通专用", 1.8e8, 0.0385, None, None, why],
                        ["机构专用", 7.0e7, 0.015, 1.0e7, 0.002, why],
                        ["机构专用", 5.0e7, 0.010, 3.0e7, 0.006, why],
                        ["某证券营业部", 2.0e7, 0.004, None, None, why]], columns=cols)
    sell = pd.DataFrame([["沪股通专用", None, None, 9.0e7, 0.019, why],
                         ["机构专用", 5.0e7, 0.010, 3.0e7, 0.006, why]], columns=cols)
    r = extras.lhb_seats("600206", None, fetch=lambda flag: buy if flag == "买入" else sell)
    g = r["groups"][0]
    assert r["available"] and g["reason"] == why
    hk = g["buy"][0]
    assert (hk["kind"], hk["buy"], hk["sell"], hk["net"], hk["buy_share"]) == ("北向", 1.8e8, 9.0e7, 9.0e7, 3.85)
    assert g["sell"][0]["net"] == 9.0e7, "the same seat, the same net, in either list"
    assert g["inst_net"] == 6.0e7 + 2.0e7, "each institution once: 6000万 + 2000万"
    assert (g["top_buy"], g["top_sell"]) == (3.2e8, 1.3e8), "every listed seat once, both sides of each"
    none = extras.lhb_seats("600206", None, fetch=lambda flag: pd.DataFrame())
    assert not none["available"]
    client = TestClient(create_app(RunManager(runner=lambda r, e: None), reports_root=tmp_path, watchlist_path=tmp_path / "w.json"))
    assert client.get("/api/market/lhb/60020x").status_code == 400



def test_boards_split_the_day_by_board(monkeypatch):
    import pandas as pd

    from web.server import market

    rows = pd.DataFrame({"code": ["600001", "000002", "300003", "688004", "920005", "830006"],
                         "name": ["甲", "乙", "丙", "丁", "戊", "己"], "pre_close": 10.0,
                         "close": [11.0, 9.0, 10.5, 9.5, 13.0, 10.0], "high": [11.0, 9.5, 10.5, 9.8, 13.0, 10.0],
                         "pct_chg": [10.0, -10.0, 5.0, -5.0, 30.0, 0.0], "amount": [4e8, 1e8, 2e8, 2e8, 0.5e8, 0.5e8]})
    monkeypatch.setattr(market, "cross_section", lambda date: ("2026-11-18", rows))
    assert market.board_of(rows["code"]).tolist() == ["主板", "主板", "创业板", "科创板", "北交所", "北交所"]
    b = {x["board"]: x for x in market.boards()["boards"]}
    assert (b["主板"]["count"], b["主板"]["limit_up"], b["主板"]["limit_down"], b["主板"]["amount_share"]) == (2, 1, 1, 50.0)
    assert (b["北交所"]["up"], b["北交所"]["flat"], b["北交所"]["limit_up"]) == (1, 1, 1)
    assert b["创业板"]["median"] == 5.0


def test_concepts_and_forecasts(monkeypatch):
    import pandas as pd

    from web.server import extras, market

    monkeypatch.setattr(market, "_days_on_record", lambda end: [d for d in ("2026-11-17", "2026-11-18") if not end or d <= end])
    monkeypatch.setattr(market, "last_closed_day", lambda: "2026-11-18")
    now = pd.DataFrame({"行业": ["F5G概念", "CRO概念"], "行业-涨跌幅": [2.81, -3.2], "流入资金": [186.3, 10.0],
                        "流出资金": [164.83, 15.0], "净额": [21.47, -5.0], "公司家数": [36, 20],
                        "领涨股": ["平治信息", "某某"], "领涨股-涨跌幅": [13.95, 1.0]})
    c = extras.concepts(None, "1d", fetch=lambda: now)
    assert c["available"] and (c["count"], c["up"]) == (2, 1)
    assert c["concepts"][0] == {"name": "F5G概念", "pct": 2.81, "count": 36, "inflow": 186.3e8, "outflow": 164.83e8,
                                "net": 21.47e8, "leader": "平治信息", "leader_pct": 13.95}
    five = pd.DataFrame({"行业": ["证金持股"], "阶段涨跌幅": ["1.77%"], "流入资金": [90.23], "流出资金": [113.22],
                         "净额": [-22.99], "公司家数": [33]})
    assert extras.concepts(None, "5d", fetch=lambda: five)["concepts"][0]["pct"] == 1.77
    assert not extras.concepts("2026-11-17", "1d", fetch=lambda: now)["available"], "only the latest day"
    with pytest.raises(ValueError):
        extras.concepts(None, "3d", fetch=lambda: now)

    monkeypatch.setattr(market, "industries", lambda: pd.DataFrame({"sw1": ["电子", "电子", "银行"]},
                                                                    index=["000001", "000002", "000003"]))
    q3 = pd.DataFrame({
        "股票代码": ["000001", "000001", "000002", "000003", "000004"],
        "股票简称": ["甲", "甲", "乙", "丙", "丁"],
        "预测指标": ["归属于上市公司股东的净利润", "营业收入", "归属于上市公司股东的净利润", "归属于上市公司股东的净利润",
                     "扣除非经常性损益后的净利润"],
        "业绩变动": ["盈利增长", "收入增长", "亏损", "扭亏", "扣非"], "业绩变动幅度": [120.0, 30.0, -50.0, None, 10.0],
        "预告类型": ["预增", "略增", "首亏", "扭亏", "预增"], "公告日期": ["2026-10-10", "2026-10-10", "2026-10-20", "2026-11-19", "2026-10-01"]})
    f = extras.forecasts(None, "2026-09-30", table=lambda p: q3)
    assert f["available"] and f["period"] == "2026-09-30"
    assert f["count"] == 2, "one net-profit forecast a stock; one announced after the day left out; 扣非 not counted"
    assert (f["good"], f["good_share"]) == (1, 50.0)
    assert [t["type"] for t in f["types"]] == ["预增", "首亏"]
    assert f["industries"] == [{"name": "电子", "count": 2, "good": 1, "good_share": 50.0, "median_chg": 35.0}]
    assert [x["name"] for x in f["best"]] == ["甲", "乙"] and f["latest"][0]["name"] == "乙"
    picked = extras.forecasts(None, table=lambda p: q3 if p == pd.Timestamp("2026-09-30") else q3.iloc[:0])
    assert picked["period"] == "2026-09-30", "without a period: the one with forecasts"
    h1 = q3.assign(公告日期="2026-08-01")
    both = lambda p: q3 if p == pd.Timestamp("2026-09-30") else h1 if p == pd.Timestamp("2026-06-30") else q3.iloc[:0]  # noqa: E731
    chose = extras.forecasts(None, "2026-06-30", table=both)
    assert chose["period"] == "2026-06-30"
    assert set(chose["periods"]) == {"2026-09-30", "2026-06-30"}, "a period picked: the others still listed, to pick again"


def test_concept_stocks_are_kept_locally_and_checked_monthly(monkeypatch, tmp_path):
    import pandas as pd

    from web.server import concepts, market

    today = {"d": "2026-11-18"}
    monkeypatch.setattr(concepts, "_dir", lambda: tmp_path / "concepts")
    monkeypatch.setattr(concepts, "_today", lambda: today["d"])
    monkeypatch.setattr(market, "cross_section", lambda date=None: ("2026-11-18", pd.DataFrame(
        {"code": ["000001", "000002", "000003"], "pct_chg": [2.0, -1.0, 5.0], "close": [10.0, 20.0, 30.0], "amount": 1e8})))
    monkeypatch.setattr(market, "industries", lambda: pd.DataFrame({"sw1": ["通信", "电子", "通信"]}, index=["000001", "000002", "000003"]))
    names = pd.DataFrame({"板块名称": ["F5G概念", "算力租赁"], "板块代码": ["BK1001", "BK1002"]})
    calls = []

    def cons(rows):
        def fetch(code):
            calls.append(code)
            return pd.DataFrame({"代码": [r[0] for r in rows], "名称": [r[1] for r in rows]})
        return fetch

    # Matching: exactly, else loosely (a trailing 概念, full-width forms, spaces).
    assert concepts.match("F5G概念", concepts.em_names(lambda: names))[2] == "exact"
    assert concepts.match("算力租赁概念", concepts.em_names())[:2] == ("算力租赁", "BK1002"), "names read from disk"
    assert concepts.match("ＦＧ５ 概念", concepts.em_names()) is None
    gone = concepts.board("不存在的概念", names_fetch=lambda: names, sina_names_fetch=lambda: pd.DataFrame({"板块": ["5G概念"], "label": ["gn_5Ggn"]}))
    assert not gone["available"] and [t["source"] for t in gone["tried"]] == ["东方财富", "同花顺", "新浪"]
    assert "东方财富没有" in gone["note"] and "同花顺：不提供" in gone["note"] and "新浪没有" in gone["note"]

    first = cons([("000001", "甲"), ("000002", "乙")])
    b = concepts.board("F5G概念", cons_fetch=first)
    assert b["available"] and b["source"] == "network" and calls == ["BK1001"]
    assert [x["code"] for x in b["stocks"]] == ["000001", "000002"] and b["stocks"][0]["industry"] == "通信"
    assert (b["up"], b["down"], b["last_change"]) == (1, 1, None)

    # Within a month: from disk, no request.
    today["d"] = "2026-12-10"
    assert concepts.board("F5G概念", cons_fetch=first)["source"] == "cache" and calls == ["BK1001"]

    # A month on: fetched again and compared; what was added and removed is kept.
    today["d"] = "2026-12-20"
    later = cons([("000001", "甲"), ("000003", "丙")])
    b = concepts.board("F5G概念", names_fetch=lambda: names, cons_fetch=later)     # the board list is a month old too
    assert b["source"] == "network" and [x["code"] for x in b["stocks"]] == ["000003", "000001"]
    assert b["last_change"] == {"date": "2026-12-20", "added": [{"code": "000003", "name": "丙"}],
                                "removed": [{"code": "000002", "name": "乙"}]}

    # Eastmoney down: what is on disk, however old.
    today["d"] = "2027-03-01"

    def down(code):
        raise ConnectionError("Push2RateLimitError")
    b = concepts.board("F5G概念", names_fetch=lambda: down(None), cons_fetch=down)
    assert b["source"] == "stale" and b["count"] == 2, "the board list and the stocks both from disk"

    # The monthly check: due boards re-fetched, stopping at the first failure.
    assert concepts.refresh_due(pause=0, fetch=down) == {"due": 1, "checked": 0, "changed": [], "stopped": "ConnectionError"}
    r = concepts.refresh_due(pause=0, fetch=cons([("000003", "丙")]))
    assert (r["due"], r["checked"]) == (1, 1) and r["changed"][0]["removed"] == [{"code": "000001", "name": "甲"}]
    assert concepts.refresh_due(pause=0)["due"] == 0, "checked today: nothing due"



def test_concept_stocks_fall_back_to_sina(monkeypatch, tmp_path):
    import pandas as pd

    from web.server import concepts, market

    monkeypatch.setattr(concepts, "_dir", lambda: tmp_path / "concepts")
    monkeypatch.setattr(concepts, "_today", lambda: "2026-11-18")
    monkeypatch.setattr(market, "cross_section", lambda date=None: ("2026-11-18", pd.DataFrame(
        {"code": ["600050", "000063"], "pct_chg": [2.5, 1.0], "close": [4.53, 30.0], "amount": 1e9})))
    monkeypatch.setattr(market, "industries", lambda: pd.DataFrame({"sw1": ["通信", "通信"]}, index=["600050", "000063"]))

    def down(*a):
        raise ConnectionError("Push2RateLimitError")
    sina_list = pd.DataFrame({"板块": ["5G概念", "华为概念"], "label": ["gn_5Ggn", "gn_hwgn"]})
    asked = []

    def sina_cons(code):
        asked.append(code)
        return pd.DataFrame({"代码": ["600050", "000063"], "名称": ["中国联通", "中兴通讯"]})

    # Eastmoney rate-limited: Sina's board of the same name.
    b = concepts.board("5G概念", names_fetch=down, cons_fetch=down, sina_names_fetch=lambda: sina_list, sina_cons_fetch=sina_cons)
    assert b["available"] and b["provider"] == "sina" and "东方财富" in b["provider_note"]
    assert asked == ["sina_gn_5Ggn"] and [x["name"] for x in b["stocks"]] == ["中国联通", "中兴通讯"]
    # Kept locally like Eastmoney's: the next look is from disk.
    again = concepts.board("5G概念", names_fetch=down, cons_fetch=down, sina_cons_fetch=sina_cons)
    assert again["source"] == "cache" and asked == ["sina_gn_5Ggn"]

    # Eastmoney up but without the concept: Sina's too.
    em = pd.DataFrame({"板块名称": ["算力租赁"], "板块代码": ["BK1002"]})
    monkeypatch.setattr(concepts, "_today", lambda: "2026-12-30")        # both lists a month old: fetched again
    hw = concepts.board("华为概念", names_fetch=lambda: em, cons_fetch=down, sina_names_fetch=lambda: sina_list, sina_cons_fetch=sina_cons)
    assert hw["provider"] == "sina" and "东方财富没有" in hw["provider_note"]
    # The monthly check covers Sina's boards too.
    assert concepts.refresh_due(pause=0, fetch=sina_cons)["due"] == 1, "5G概念 checked a month ago"


def test_v8_is_entered_by_one_thread_at_a_time():
    import threading
    import time

    from py_mini_racer import MiniRacer

    from web.server import v8guard

    assert v8guard.install() and MiniRacer._v8guard, "installed when web.server is imported"
    assert MiniRacer().eval("1 + 1") == 2

    inside, most = [0], [0]
    count = threading.Lock()

    class Engine:               # stands in for MiniRacer: how many threads are in it at once
        def _enter(self):
            with count:
                inside[0] += 1
                most[0] = max(most[0], inside[0])
            time.sleep(0.005)
            with count:
                inside[0] -= 1

        def __init__(self):
            self._enter()

        def eval(self, code):
            self._enter()
            return code

        def call(self, name):
            self._enter()
            return name
    v8guard.wrap(Engine)

    def run():
        for _ in range(5):
            e = Engine()
            e.eval("x")
            e.call("v")
    threads = [threading.Thread(target=run) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert most[0] == 1, "never two threads inside"
    assert v8guard.wrap(Engine) is Engine and Engine.eval.__wrapped__.__name__ == "eval", "wrapped once"



def test_breadth_thrust_fires_once_when_the_ema_jumps_from_low_to_high():
    import pandas as pd

    from web.server import breadth

    days = pd.RangeIndex(30)
    ema = pd.Series([0.5] * 5 + [0.38, 0.45, 0.55, 0.62, 0.64, 0.6, 0.63]     # under 0.40, over 0.615 4 days on
                    + [0.5] * 6 + [0.39] + [0.5] * 10 + [0.62], index=days)   # over again, but 11 days after the low
    fired = breadth.thrust_signals(ema)
    assert list(fired[fired].index) == [8], "once, on the day it crossed; not again while still high nor too late"



def test_msi_does_not_depend_on_where_the_history_starts():
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(7)
    ratio = pd.Series(rng.normal(0, 300, 400))

    def msi(r):
        return 19 * r.ewm(span=39, adjust=False).mean() - 9 * r.ewm(span=19, adjust=False).mean()

    def running_sum(r):
        return (r.ewm(span=19, adjust=False).mean() - r.ewm(span=39, adjust=False).mean()).cumsum()
    late = ratio.iloc[150:]
    closed = (msi(ratio).loc[late.index] - msi(late)).abs()
    summed = (running_sum(ratio).loc[late.index] - running_sum(late)).abs()
    # The closed form forgets its start (the EMAs' memory fading); a running sum never does.
    assert closed.iloc[-1] < 0.05 and closed.iloc[-1] < closed.iloc[-60], "the closed form: one MSI, whatever the start"
    assert summed.iloc[-60:].min() > 100 * closed.iloc[-60:].max(), "a running sum: one per start"
    gap = running_sum(ratio) - msi(ratio)
    assert gap.std() < 1e-9 * msi(ratio).std(), "exactly the running sum, up to a constant"


def test_breadth_verdict_judges_each_state_by_its_own_past_only(monkeypatch):
    import numpy as np
    import pandas as pd

    from web.server import breadth_verdict as bv, market

    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2025-01-01", periods=260)]
    rng = np.random.default_rng(3)
    table = pd.DataFrame({
        "mcl_sum": np.cumsum(rng.normal(0, 50, 260)), "mcl_osc": rng.normal(0, 40, 260),
        "thrust": rng.uniform(0.3, 0.7, 260), "thrust_signal": False,
        "adr10": rng.uniform(0.5, 1.5, 260), "adr10_rank": rng.uniform(0, 100, 260),
        "trin_amt10": rng.uniform(0.5, 1.2, 260), "trin_amt10_rank": rng.uniform(0, 100, 260),
        "up_pct": rng.uniform(5, 90, 260), "trin_amt": rng.uniform(0.2, 1.8, 260), "trin_vol": rng.uniform(0.2, 1.8, 260)}, index=days)
    up = rng.integers(1000, 4000, 260)
    stats = pd.DataFrame({"date": days, "up": up, "down": 5000 - up, "flat": 50, "limit_up": 30, "limit_down": 20})
    idx = pd.Series(3000 * np.cumprod(1 + rng.normal(0, 0.01, 260)), index=days)
    monkeypatch.setattr(market, "_days_on_record", lambda end: [d for d in days if not end or d <= end])

    day = days[200]
    v = bv.verdict(day, table=table, stats=stats, idx=idx)
    assert v["date"] == day and [r["step"] for r in v["rows"]] == ["定趋势"] * 2 + ["找时机"] * 3 + ["验真伪"] * 2
    assert v["history_to"] <= days[200 - 20], "only days whose 20 days had passed by the day asked about"
    # The same answer whatever came after: the future cannot leak in.
    later = idx.copy()
    later.iloc[201:] *= 2
    assert bv.verdict(day, table=table, stats=stats, idx=later)["rows"] == v["rows"]
    for r in v["rows"]:
        assert r["lean"] in {"偏多", "短期偏多", "中性", "短期偏空", "偏空", "无数据"} and "基准" in r["reason"]
    assert v["conclusion"]["short_word"] and v["conclusion"]["watch"] and v["conclusion"]["summary"].startswith("短期（5 日）")
    assert [p[0] for p in v["conclusion"]["points"]] == ["①", "②", "③"], "one line a step"
    assert len(v["structure"]["rows"]) == 10 and sum(r["today"] for r in v["structure"]["rows"]) <= 1
    rd = v["structure"]["readings"]
    assert (rd["up"] + rd["down"], rd["flat"], rd["adl_day"]) == (5000, 50, rd["up"] - rd["down"])
    assert (rd["limit_up"], rd["limit_down"]) == (30, 20) and rd["up_amt_pct"] is None, "no amount shares in this table"

    # 当日市场结构 day by day, the newest first, as many days as asked for.
    sd = bv.structure_days(days[230], "10d", table=table, stats=stats)
    assert [x["date"] for x in sd["days"]] == days[221:231][::-1]
    assert sd["days"][0]["limit_up"] == 30 and sd["days"][0]["up"] + sd["days"][0]["down"] == 5000
    assert len(bv.structure_days(days[230], "1d", table=table, stats=stats)["days"]) == 1
    with pytest.raises(ValueError):
        bv.structure_days(None, "5d", table=table, stats=stats)

    # The history: each day the card's reading as it would have been then, and how it went.
    h = bv.history(days[230], "60d", table=table, stats=stats, idx=idx)
    assert len(h["days"]) == 60 and h["end"] == days[230]
    then = next(x for x in h["days"] if x["date"] == day)
    assert (then["short"], then["mid"]) == (v["conclusion"]["short"], v["conclusion"]["mid"]), "the same reading as on the day"
    assert then["f5"] == round((idx.iloc[205] / idx.iloc[200] - 1) * 100, 2)
    assert h["days"][-1]["f5"] is None and h["days"][-6]["f5"] is not None and h["days"][-20]["f20"] is None, \
        "an outcome only once it had happened by the end of the span, though later data exists"
    acc = h["accuracy"]["short"]
    assert set(acc) == {"bull", "bear", "all_up"} and all(acc[k]["days"] >= acc[k]["right"] for k in ("bull", "bear"))
    with pytest.raises(ValueError):
        bv.history(None, "2y", table=table, stats=stats, idx=idx)

    # No index for the day yet: the divergence row says so instead of reading a stale index.
    stale = bv.verdict(day, table=table, stats=stats, idx=idx.loc[:days[190]])
    assert stale["rows"][-1]["lean"] == "无数据"


def test_breadth_verdict_leans():
    from web.server import breadth_verdict as bv

    base = {"up5": 55.0, "up20": 58.0}
    lean = lambda u5, u20: bv._lean({"days": 50, "up5": u5, "up20": u20}, base)[0]  # noqa: E731
    assert (lean(62, 66), lean(48, 50), lean(62, 58), lean(48, 60), lean(56, 59)) == ("偏多", "偏空", "短期偏多", "短期偏空", "中性")


def test_market_structure_states():
    import pandas as pd

    from web.server import breadth_verdict as bv

    # 涨家占比, TRIN_额, its rise off the 3 days' low, MCL -> the state
    cases = [(70, 0.9, 0.0, 10, "broad_up_strong"), (70, 0.9, 0.0, -10, "broad_up_rebound"), (70, 1.5, 0.0, 10, "fake_up"),
             (15, 0.46, 0.0, -5, "cluster_hold"), (20, 0.81, 0.35, -36, "cluster_break"), (20, 0.95, 0.05, -36, "broad_down"),
             (10, 1.6, 0.0, -50, "panic"), (50, 0.6, 0.0, 0, "mixed_cluster"), (50, 1.0, 0.0, 0, "mixed"),
             (50, 1.4, 0.0, 0, "mixed_out"), (None, 0.5, 0.0, 0, "")]
    up, trin, rise, mcl, want = zip(*cases, strict=False)
    got = bv.structure_states(pd.Series(up, dtype=float), pd.Series(trin), pd.Series(rise), pd.Series(mcl))
    assert got.tolist() == list(want)
    assert {k for k, *_ in bv.STRUCTURES} == set(want) - {""}, "every state has a rule and a meaning"


def test_the_store_has_a_monthly_cache_key(monkeypatch):
    import datetime as dt

    from tradingagents.dataflows.vendors.akshare import store

    monkeypatch.setattr(store, "last_closed_trade_date", lambda now=None: dt.date(2026, 11, 20))
    assert store._key("monthly") == ("2026M11", False)


def test_market_breadth_report_stops_at_the_analysis_date(monkeypatch):
    import pandas as pd

    from tradingagents.dataflows import market_breadth
    from web.server import breadth, breadth_verdict, market

    days = [f"2026-11-{d:02d}" for d in (16, 17, 18, 19, 20)]
    n = len(days)
    table = pd.DataFrame({c: [float("nan")] * n for c in breadth.columns()}, index=days)
    table["up_pct"] = [70.0, 20.0, 20.0, 30.0, 5.6]
    table["trin_amt"] = [0.9, 0.5, 0.4, 0.3, 0.27]
    table["trin_vol"] = [0.9, 0.6, 0.5, 0.4, 0.22]
    table["mcl_osc"] = [1.0, -1.0, -2.0, -3.0, -4.0]
    table["mcl_raw"] = [10.0, -20.0, -30.0, -40.0, -642.7]
    table["amt_gap"] = [1.0, 2.0, 3.0, 4.0, 12.46]
    stats = pd.DataFrame({"date": days, "up": [3500, 1000, 1000, 1500, 313], "down": [1500, 4000, 4000, 3500, 5235],
                          "flat": [50] * n, "limit_up": [60, 30, 30, 30, 30], "limit_down": [5, 60, 60, 60, 68],
                          "amount": [2e12, 1.5e12, 1.4e12, 1.3e12, 1.43e12]})
    monkeypatch.setattr(market, "_days_on_record", lambda end: [d for d in days if d <= end])
    monkeypatch.setattr(market, "_span_stats", lambda span: (stats, None))
    monkeypatch.setattr(market, "index_closes", lambda name: pd.DataFrame({"date": days, "close": [3602.57, 3584.58, 3587.83, 3577.62, 3533.79]}))
    monkeypatch.setattr(breadth, "_key", lambda: ("k",))
    monkeypatch.setattr(breadth, "_table", lambda key: table)
    monkeypatch.setattr(breadth_verdict, "verdict", lambda d: (_ for _ in ()).throw(LookupError("no index")))

    text = market_breadth.get_market_breadth("2026-11-19", 10)
    assert "2026-11-19" in text and "2026-11-20" not in text           # nothing after the analysis date
    assert "| 2026-11-16 | 3602.57" in text and "放量" not in text.split("## Market structure")[0].split("2026-11-17")[0]
    last = market_breadth.get_market_breadth("2026-11-20", 2)
    assert "2026-11-18" not in last.split("## Day by day")[1].split("## Market")[0]   # two days only
    assert "| 313/5235/50 | 5.60%" in last and "| 0.270 | 0.220 |" in last and "-642.7" in last and "30/68" in last
    assert "## Market structure on 2026-11-20: 少数股抱团" in last


def test_industry_context_ranks_the_stock_among_its_peers(monkeypatch):
    from tradingagents.dataflows import market_context
    from web.server import market, sectors

    def row(code, name, pct, p5, pe, mv, l3="数字芯片设计"):
        return {"code": code, "name": name, "pct_chg": pct, "pct_5d": p5, "pe_ttm": pe, "total_mv": mv,
                "industry": "电子", "sub_industry": "半导体", "industry3": l3}
    rows = [row("688256", "寒武纪", -1.5, -6.0, 138.8, 5e11), row("688041", "海光信息", -7.0, -15.0, 37.7, 6e11),
            row("688521", "芯原股份", -8.0, -16.0, -5.0, 1e11), row("603501", "豪威集团", -3.0, -3.4, 30.0, 1.5e11, "模拟芯片设计")]
    monkeypatch.setattr(market, "_days_on_record", lambda end: ["2026-11-19", "2026-11-20"])
    monkeypatch.setattr(market, "market_table", lambda day: {"rows": rows})
    monkeypatch.setattr(sectors, "sectors", lambda end, days, level: {"industries": (
        [{"name": "电子", "cum5": -9.23, "cum20": -17.6, "pe": 34.5, "pe_rank": 22, "pb_rank": 60, "dy": 0.53},
         {"name": "银行", "cum5": 1.0, "cum20": 3.0, "pe": 6.0, "pe_rank": 50, "pb_rank": 40, "dy": 5.0}]
        if level == "sw1" else [{"name": "电子-半导体", "cum5": -8.35, "cum20": -13.73, "pe": 39.8, "pe_rank": 6, "pb_rank": 65, "dy": 0.23}])})
    monkeypatch.setattr(sectors, "crowding", lambda end: (_ for _ in ()).throw(ConnectionError("down")))

    text = market_context.get_industry_context("688256.SS", "2026-11-20")
    assert "一级 电子 · 二级 半导体 · 三级 数字芯片设计" in text
    # 三级: three peers; 寒武纪 is the strongest today and over 5 days, second by market value;
    # the peers' P/E median leaves out the loss-maker.
    assert "| 三级 数字芯片设计 | 3 | -7.00% | 1/3 | -15.00% | 1/3 | 88.2 | 2/3 |" in text
    assert "| 一级 电子 | 4 |" in text and "| 电子 | -9.23% | -17.60% | 2/2 | 34.5 | 22% |" in text
    assert "| 电子-半导体 | -8.35% |" in text
    assert "## 行业拥挤度" in text and "unavailable: ConnectionError" in text     # one section down, the rest stand
    assert "only" in market_context.get_industry_context("NVDA", "2026-11-20")


def test_market_temperature_marks_the_stocks_own_limit_ups(monkeypatch):
    import pandas as pd

    from tradingagents.dataflows import market_context
    from web.server import breadth, extras, limit_detail, market, sectors

    days = ["2026-11-19", "2026-11-20"]
    table = pd.DataFrame({"mood": [34.0, 35.0], **{f"m_{k}": [10.0, 20.0] for k in breadth.MOOD_PARTS}}, index=days)
    monkeypatch.setattr(market, "_days_on_record", lambda end: [d for d in days if d <= end])
    monkeypatch.setattr(breadth, "_key", lambda: ("k",))
    monkeypatch.setattr(breadth, "_table", lambda key: table)
    monkeypatch.setattr(extras, "qvix", lambda end, rng: {"since": "2015-02-09", "rank": 14, "median": 19.25,
                                                         "days": [{"date": "2026-11-18", "close": 14.8}]})
    monkeypatch.setattr(extras, "margin", lambda end, rng: {"days": [{"date": "2026-11-18", "total": 2.2306e12},
                                                                    {"date": "2026-11-19", "total": 2.2151e12}]})
    monkeypatch.setattr(sectors, "valuation", lambda end: {"days": [
        {"date": "2005-01-04", "pe": 21.0, "pb": 2.0, "dy": 1.2, "y10": 5.2, "erp": -0.5},
        {"date": "2026-11-20", "pe": 15.0, "pb": 1.66, "dy": 1.92, "y10": 1.58, "erp": 5.09}]})
    monkeypatch.setattr(extras, "themes", lambda date, n, top=10: {"date": "2026-11-20", "dates": days, "have": days,
                        "themes": [{"name": "光刻胶", "today": 2, "total": 7, "days_on": 2,
                                    "stocks": [{"code": "603004"}, {"code": "688256"}]}]})
    monkeypatch.setattr(limit_detail, "details", lambda d: pd.DataFrame(
        {"code": ["688256"], "reason": ["光刻胶+AI芯片"]}) if d == "2026-11-20" else pd.DataFrame())

    text = market_context.get_market_temperature("2026-11-20", "688256.SS")
    assert "| 2026-11-20 | 35 | 20 |" in text and "QVIX" in text and "14% 分位" in text
    assert "较 1 日前 -155亿" in text and "ERP（1/PE − 国债收益率）5.09%" in text
    assert "- 光刻胶: 2 / 7 / 2 天 ← 本股当日涨停属此题材" in text
    assert "2026-11-20 涨停（光刻胶+AI芯片）" in text
    earlier = market_context.get_market_temperature("2026-11-19", "688256.SS")
    assert "| 2026-11-20 |" not in earlier and "temperature to 2026-11-19" in earlier   # nothing after the date


def test_margin_trend_reads_the_slope_and_a_turn():
    import pandas as pd

    from tradingagents.dataflows import market_context

    def series(values):
        return pd.Series([v * 1e8 for v in values], dtype=float, index=[f"d{i}" for i in range(len(values))])

    steady = series([100 + 2 * i for i in range(25)])
    assert market_context._slope(steady) == pytest.approx(2e8)
    assert "20 日斜率 +2.0亿/日，近 5 日 +2.0亿/日，加杠杆放缓" in market_context.margin_trend(steady)[0]

    accel = series([100 + i for i in range(20)] + [119 + 4 * i for i in range(1, 6)])
    assert "加杠杆加快" in market_context.margin_trend(accel)[0]

    turn = series([100 + 2 * i for i in range(20)] + [136, 134, 132, 130, 128])
    assert "由增转减（去杠杆）" in market_context.margin_trend(turn)[0]
    assert market_context.margin_trend(series([100, 101])) == []      # too short for a slope


def test_policy_events_appear_only_from_their_announcement(monkeypatch):
    import pandas as pd

    from tradingagents.dataflows import market_context, policy_events
    from web.server import breadth, extras, limit_detail, market, sectors

    # the new measure is not visible to a run dated before its announcement
    assert [e.effective for e in policy_events.events_between("2026-11-21")] == []
    assert [(e.effective, e.announced) for e in policy_events.events_between("2026-11-22")] == [("2026-11-30", "2026-11-22")]
    assert policy_events.events_between("2027-06-01") == []               # and fades out once it is old

    days = ["2026-11-20", "2026-11-21", "2026-11-22", "2026-11-25"]
    table = pd.DataFrame({"mood": [34.0] * 4, **{f"m_{k}": [10.0] * 4 for k in breadth.MOOD_PARTS}}, index=days)
    monkeypatch.setattr(market, "_days_on_record", lambda end: [d for d in days if d <= end])
    monkeypatch.setattr(market, "industries", lambda: pd.DataFrame(
        {"sw1": ["非银金融"], "sw2": ["证券Ⅱ"], "sw3": ["证券Ⅲ"]}, index=["600030"]))
    monkeypatch.setattr(breadth, "_key", lambda: ("k",))
    monkeypatch.setattr(breadth, "_table", lambda key: table)
    monkeypatch.setattr(extras, "qvix", lambda end, rng: {"since": "s", "rank": 1, "median": 1.0,
                                                         "days": [{"date": days[0], "close": 14.8}]})
    monkeypatch.setattr(extras, "margin", lambda end, rng: {"days": [{"date": d, "total": 2.2e12} for d in days]})
    monkeypatch.setattr(sectors, "valuation", lambda end: {"days": [
        {"date": "2005-01-04", "pe": 21.0, "pb": 2.0, "dy": 1.2, "y10": 5.2, "erp": -0.5},
        {"date": "2026-11-20", "pe": 15.0, "pb": 1.66, "dy": 1.92, "y10": 1.58, "erp": 5.09}]})
    monkeypatch.setattr(extras, "themes", lambda date, n, top=10: {"date": days[0], "dates": days, "have": days,
                        "themes": []})
    monkeypatch.setattr(limit_detail, "details", lambda d: pd.DataFrame())

    assert "## 政策与事件" not in market_context.get_market_temperature("2026-11-21", "600030.SS")
    text = market_context.get_market_temperature("2026-11-22", "600030.SS")
    assert "## 政策与事件" in text
    assert "2026-11-30（2026-11-22 公布，8 天后生效）【两融】" in text
    assert "融资保证金比例下限 100% → 80%" in text and "← 本股所在行业" in text
    assert "较 1 日前 +0亿" in text and "两融趋势" in text
    assert "5 天后生效" in market_context.get_market_temperature("2026-11-25", "600030.SS")


def test_the_rebound_endpoint_serves_a_shares_only_and_stops_at_end(env, monkeypatch):
    from tradingagents.dataflows import market_context

    seen = {}

    def fake(code, end=None):
        seen.update(code=code, end=end)
        return {"signals": [], "now": None, "market": None, "rule": "r", "stats": "s"}
    monkeypatch.setattr(market_context, "rebound_data", fake)
    client = env[0]
    assert client.get("/api/stock/600519.SS/rebound?end=2026-11-13").json()["rule"] == "r"
    assert seen == {"code": "600519", "end": "2026-11-13"}
    assert client.get("/api/stock/NVDA/rebound").status_code == 404


def test_rebound_data_flags_the_sell_that_closes_a_trade(monkeypatch):
    import numpy as np
    import pandas as pd

    from tradingagents.dataflows import market_context
    from web.server import breadth, market

    calm = 100 + np.sin(np.arange(80) / 3)
    slide = calm[-1] * np.cumprod(np.full(25, 0.97))
    bounce = slide[-1] * np.cumprod([1.04, 1.03, 1.02, 1.01, 1.0, 1.0, 1.0, 1.0])
    closes = np.r_[calm, slide, bounce, bounce[-1] * np.cumprod(np.full(40, 1.02))]
    days = pd.bdate_range("2024-01-02", periods=len(closes)).strftime("%Y-%m-%d")
    prev = np.r_[closes[0], closes[:-1]]
    amount = np.r_[np.full(105, 1e8), np.full(8, 2e8), np.full(40, 1e8)]
    bars = [{"time": d, "open": float(p), "high": float(max(p, c) * 1.005), "low": float(min(p, c) * 0.995),
             "close": float(c), "volume": 1e5, "amount": float(a), "pct_chg": float((c / p - 1) * 100)}
            for d, p, c, a in zip(days, prev, closes, amount, strict=True)]
    monkeypatch.setattr(market, "history", lambda code, end=None: {"bars": bars})
    monkeypatch.setattr(breadth, "_key", lambda: ("k",))
    # The market's MCL rising every day: each 反 is purple, so the first is bought.
    monkeypatch.setattr(breadth, "_table", lambda key: pd.DataFrame({"mcl_osc": np.arange(len(days), dtype=float)},
                                                                     index=list(days)))
    # A sell signal three days after the buy, before the +25% target: the trade is sold by 卖.
    from tradingagents.dataflows import rebound_signal as rs
    real = rs._sell_condition
    first = rs.signals(pd.DataFrame(bars).rename(columns={"time": "date"})).iloc[0]["date"]
    on = list(days)[list(days).index(first) + 3]
    monkeypatch.setattr(rs, "_sell_condition", lambda x: real(x) | (x["date"] == on))
    d = market_context.rebound_data("600519")
    trade = d["signals"][0]["trade"]
    assert trade["exit"] == "卖" and trade["sell_date"] == on and trade["peak_ret"] is not None
    closing = [s for s in d["sells"] if s["closes"]]
    assert [s["date"] for s in closing] == [trade["sell_date"]]
    assert all(not s["closes"] for s in d["sells"] if s["date"] != trade["sell_date"])


def test_rebound_buys_one_position_at_a_time_on_purple_only(monkeypatch):
    import pandas as pd

    from tradingagents.dataflows import market_context, rebound_signal as rs
    from web.server import breadth, market

    days = sorted({f"2026-0{m}-{d:02d}" for m in range(1, 7) for d in (5, 20)}
                  | set(pd.bdate_range("2025-09-01", periods=60).strftime("%Y-%m-%d")))
    bars = [{"time": d, "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1.0, "amount": 1.0,
             "pct_chg": 0.0} for d in days]
    monkeypatch.setattr(market, "history", lambda code, end=None: {"bars": bars})
    monkeypatch.setattr(breadth, "_key", lambda: ("k",))
    monkeypatch.setattr(breadth, "_table", lambda key: pd.DataFrame({"mcl_osc": []}))
    sig = pd.DataFrame({"date": ["2026-01-05", "2026-01-20", "2026-03-05", "2026-04-05"],
                        "market_ok": pd.Series([True, True, False, True], dtype=object)})
    for c in ("trigger", "oversold"):
        sig[c] = "x"
    for c in ("adx", "mdi", "pdi", "amt_ratio", "close", "stop"):
        sig[c] = 1.0
    trades = pd.DataFrame({
        "date": sig["date"], "entry_date": ["2026-01-20", "2026-02-05", "2026-03-20", "2026-04-20"],
        "exit_date": ["2026-03-20", "2026-03-20", "2026-03-20", None],
        "sell_date": ["2026-03-05", "2026-03-05", "2026-03-05", None],
        "exit": ["卖", "卖", "卖", "持有中"], "ret": [5.0, 3.0, 1.0, -2.0], "days": [40, 30, 0, 30],
        "peak_date": [None] * 4, "peak_ret": [None] * 4})
    monkeypatch.setattr(rs, "signals", lambda b, m=None: sig)
    monkeypatch.setattr(rs, "exits", lambda b, s, *rule: trades)
    monkeypatch.setattr(rs, "sell_signals", lambda b, m=None, include=None: pd.DataFrame(
        {"date": ["2026-03-05", "2026-05-05"], "reason": "r", "gain20": 31.0, "adx": 30.0, "close": 10.0,
         "market_weak": pd.Series([None, None], dtype=object)}))
    d = market_context.rebound_data("600519")
    got = {s["date"]: (s["trade"] is not None, s["skip"]) for s in d["signals"]}
    assert got["2026-01-05"] == (True, None)                         # bought
    assert got["2026-01-20"] == (False, "持仓中，不重复买入")          # purple, but the first is still held
    assert got["2026-03-05"] == (False, "市场条件不满足，不买")        # grey
    assert got["2026-04-05"] == (True, None)                         # sold on 03-20: free again
    assert [s["date"] for s in d["sells"] if s["closes"]] == ["2026-03-05"]   # the one sale; 05-05 is 避


def test_rebound_data_carries_the_best_per_trade_rule_with_its_own_book(monkeypatch):
    import numpy as np
    import pandas as pd

    from tradingagents.dataflows import market_context, rebound_signal as rs
    from web.server import breadth, market

    calm = 100 + np.sin(np.arange(80) / 3)
    slide = calm[-1] * np.cumprod(np.full(25, 0.97))
    bounce = slide[-1] * np.cumprod([1.04, 1.03, 1.02, 1.01, 1.0, 1.0, 1.0, 1.0])
    closes = np.r_[calm, slide, bounce, bounce[-1] * np.cumprod(np.full(40, 1.01))]   # +1% a day: +25% in ~23 days
    days = pd.bdate_range("2024-01-02", periods=len(closes)).strftime("%Y-%m-%d")
    prev = np.r_[closes[0], closes[:-1]]
    amount = np.r_[np.full(105, 1e8), np.full(8, 2e8), np.full(40, 1e8)]
    bars = [{"time": d, "open": float(p), "high": float(max(p, c) * 1.005), "low": float(min(p, c) * 0.995),
             "close": float(c), "volume": 1e5, "amount": float(a), "pct_chg": float((c / p - 1) * 100)}
            for d, p, c, a in zip(days, prev, closes, amount, strict=True)]
    monkeypatch.setattr(market, "history", lambda code, end=None: {"bars": bars})
    monkeypatch.setattr(breadth, "_key", lambda: ("k",))
    monkeypatch.setattr(breadth, "_table", lambda key: pd.DataFrame({"mcl_osc": np.arange(len(days), dtype=float)},
                                                                     index=list(days)))
    monkeypatch.setattr(rs, "_sell_condition", lambda x: pd.Series(False, index=x.index))
    d = market_context.rebound_data("600519")
    short = d["signals"][0]["trade"]
    best = d["best"]["trades"][0]
    assert best["date"] == d["signals"][0]["date"] and best["entry_date"] == short["entry_date"]
    assert short["exit"] == "期" and short["days"] == rs.MAX_DAYS            # the short rule: sold after 20 days
    assert best["exit"] == "盈" and best["ret"] == pytest.approx(rs.BEST_TAKE_PROFIT * 100, abs=0.05)  # held to +25%
    assert "单笔最优" in d["best"]["rule"]


def test_intraday_keeps_the_last_days_and_measures_against_the_close_before(env):
    import pandas as pd

    from web.server import intraday

    rows = []
    for d, base in (("2026-11-12", 10.0), ("2026-11-13", 11.0), ("2026-11-16", 12.0)):
        for i, hm in enumerate(("09:31:00", "09:32:00", "15:00:00")):
            rows.append({"day": f"{d} {hm}", "open": base, "high": base + 0.2, "low": base - 0.2,
                         "close": base + i * 0.1, "volume": 100.0 * (i + 1), "amount": (base + i * 0.1) * 100 * (i + 1)})
    fetch = lambda sym: pd.DataFrame(rows)      # noqa: E731
    out = intraday.intraday("600519", 2, fetch=fetch)
    assert [d["date"] for d in out["days"]] == ["2026-11-13", "2026-11-16"]     # the last two days
    assert out["prev_close"] == 10.2                                           # 11-12's last close
    first = out["days"][0]["points"]
    assert first[0]["time"] == "09:31" and first[0]["price"] == 11.0
    assert first[1]["avg"] == round((11.0 * 100 + 11.1 * 200) / 300, 3)         # running amount ÷ volume
    client = env[0]
    assert client.get("/api/stock/NVDA/intraday").status_code == 404


def test_flow_history_grows_on_disk_and_survives_a_failed_fetch(tmp_path):
    import pandas as pd

    from tradingagents.dataflows.vendors.akshare import settings as ak_settings
    from web.server import flow

    ak_settings.set_data_dir(tmp_path / ".akshare_data")
    try:
        first = lambda c: pd.DataFrame({"date": ["2026-05-28", "2026-05-29"], "main": [1e8, -2e8]})   # noqa: E731
        later = lambda c: pd.DataFrame({"date": ["2026-05-29", "2026-06-01"], "main": [-3e8, 4e8]})   # noqa: E731
        assert flow.history("688256", fetch=first)["days"] == {"2026-05-28": 1e8, "2026-05-29": -2e8}
        d = flow.history("688256", fetch=later)          # merged: the older day kept, a day re-sent updated
        assert d["days"] == {"2026-05-28": 1e8, "2026-05-29": -3e8, "2026-06-01": 4e8} and d["since"] == "2026-05-28"

        def down(c):
            raise ConnectionError("rate limited")
        d = flow.history("688256", fetch=down)           # Eastmoney down: what is kept still serves
        assert len(d["days"]) == 3 and "暂不可用" in d["note"]
    finally:
        ak_settings.set_data_dir(None)


def test_the_days_main_flow_is_kept_in_its_snapshot_and_read_back(mkt):
    import pandas as pd

    market, fake, data = mkt
    fake.stock_individual_fund_flow_rank = lambda indicator: pd.DataFrame(
        {"代码": ["300308", "600519"], "今日主力净流入-净额": [-1.2e9, 3.4e8]})
    market.market_table()                                      # 2026-11-13, closed: the flow is final
    kept = pd.read_parquet(data / "snapshots" / "20261113" / "cross_section.parquet")
    assert list(kept.columns)[-2:] == ["main_flow", "main_flow_src"]
    assert kept.set_index("code").loc["600519", "main_flow"] == 3.4e8
    # The sources gone (cache cleared, Eastmoney and 同花顺 down): the table reads the day's kept flow.
    for f in (data / "sentiment").rglob("*.pkl"):
        f.unlink()
    fake.stock_individual_fund_flow_rank = _boom
    fake.stock_fund_flow_individual = _boom
    market._TABLES.clear()
    market._read_xs.cache_clear()
    table = market.market_table()
    row = {r["code"]: r for r in table["rows"]}
    assert row["600519"]["main_flow"] == 3.4e8 and table["flow"]["source"] == "eastmoney"
    assert "本地快照" in table["flow"]["note"]


def test_ticks_fall_back_to_sina_keep_a_closed_day_and_the_auction_comes_from_them(tmp_path, monkeypatch):
    import pandas as pd

    from tradingagents.dataflows.vendors.akshare import settings as ak_settings, store
    from web.server import intraday

    ak_settings.set_data_dir(tmp_path / ".akshare_data")
    monkeypatch.setattr(store, "now_cst", lambda: pd.Timestamp("2026-11-21 10:00", tz="Asia/Shanghai"))
    monkeypatch.setattr(store, "is_intraday", lambda now=None: False)
    try:
        def em_down(code):
            raise RuntimeError("rate limited")
        sina = lambda code, day: pd.DataFrame({"time": ["09:25:00", "09:30:00", "14:57:00", "15:00:00"],  # noqa: E731
                                               "price": [230.0, 230.84, 228.5, 227.78],
                                               "volume": [556900.0, 60000.0, 1900.0, 627137.0],
                                               "side": ["卖", "买", "卖", "卖"]})
        t = intraday.ticks("300750", "2026-11-20", em=em_down, sina=sina)
        assert t["source"] == "新浪 3 秒分笔快照" and t["count"] == 4
        assert t["auction"] == {"time": "09:25:00", "price": 230.0, "volume": 556900.0}
        # The 09:25 and 15:00 call auctions have no active side: 竞价, neither bought nor sold.
        assert t["buy_volume"] == 60000.0 and t["sell_volume"] == 1900.0
        assert [r["side"] for r in t["rows"]] == ["竞价", "买", "卖", "竞价"]
        assert t["auction_count"] == 2 and t["auction_volume"] == 556900.0 + 627137.0
        # A closed day is kept on disk: no source asked the second time.
        def never(*a):
            raise AssertionError("asked again")
        assert intraday.ticks("300750", "2026-11-20", em=never, sina=never)["source"] == "新浪 3 秒分笔快照（本地缓存）"
        # The auction without Eastmoney's pre-market minutes: the 09:25 match from the trades.
        monkeypatch.setattr(intraday, "intraday", lambda code, days=5, fetch=None: {"days": [{"date": "2026-11-20"}]})
        a = intraday.auction("300750", em=em_down)
        assert a["points"] == [] and a["match"]["price"] == 230.0 and "新浪逐笔" in a["source"]
    finally:
        ak_settings.set_data_dir(None)


def test_a_finished_days_auction_minutes_are_kept_and_served_without_eastmoney(tmp_path, monkeypatch):
    import pandas as pd

    from tradingagents.dataflows.vendors.akshare import settings as ak_settings, store
    from web.server import intraday

    ak_settings.set_data_dir(tmp_path / ".akshare_data")
    monkeypatch.setattr(store, "now_cst", lambda: pd.Timestamp("2026-11-20 10:00", tz="Asia/Shanghai"))
    monkeypatch.setattr(intraday, "intraday", lambda code, days=5, fetch=None: {"days": [{"date": "2026-11-20"}]})
    try:
        # The real 09:25 match from the trade list replaces Eastmoney's last indicative price.
        monkeypatch.setattr(intraday, "ticks", lambda c, day=None, **k: {"auction": {"time": "09:25:00", "price": 232.0,
                                                                                    "volume": 556900.0}})
        minutes = [f"2026-11-20 09:{m:02d}:00" for m in range(15, 26)]
        em = lambda code: pd.DataFrame({"时间": minutes, "最新价": [231 + i * 0.1 for i in range(11)],  # noqa: E731
                                        "成交量": [10 * (i + 1) for i in range(11)]})
        a = intraday.auction("300750", em=em)
        assert len(a["points"]) == 11 and a["points"][0]["time"] == "09:15" and a["match"]["time"] == "09:25"
        assert a["points"][0]["volume"] == 1000                          # 手 → 股
        assert a["points"][-1] == {"time": "09:25", "price": 232.0, "volume": 556900.0}       # the real match
        assert a["match"]["price"] == 232.0

        def never(code):
            raise AssertionError("Eastmoney asked again")
        kept = intraday.auction("300750", em=never)
        assert kept["points"] == a["points"] and "本地保存" in kept["source"]
    finally:
        ak_settings.set_data_dir(None)
