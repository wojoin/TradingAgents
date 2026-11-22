"""The web API: start an analysis from a ticker, follow it live, read and download reports.

  GET  /api/options                     what a run can be set to, defaulting to the last run's answers
  GET  /api/market                      every A-share on ?date= (latest; any trading day): quote, industry, flow
  GET  /api/market/calendar             the trading days a date can be picked from (to the last closed one)
  GET  /api/market/stats               ?range=1d|60d|6m|1y&end=: rises, falls and amount traded, day by day
  GET  /api/market/limits              ?date=: the day's limit-ups by run length (连板), 炸板 and limit-downs
  GET  /api/market/sectors             ?days=10|20&level=sw1|sw2&end=: 申万一级 / 二级 industries' heat map and valuation
  GET  /api/market/crowding            ?end=: 行业拥挤度, the industries' turnover share and rate against their history
  GET  /api/market/valuation           ?end=: 申万A指's PE, PB and dividend yield since 2005
  GET  /api/market/margin              ?range=&end=: 两融余额 (Shanghai and Shenzhen) each trading day
  GET  /api/market/themes              ?days=3|5|10&date=: the limit-ups' themes (同花顺 涨停原因) by day
  GET  /api/market/qvix                ?range=&end=: the 50ETF volatility index (China's VIX)
  GET  /api/market/flow                ?range=&end=: the market's main-force flow (last 120 days)
  GET  /api/market/flow/industry       ?span=1d|5d|10d&date=: main-force flow by 申万 industry
  GET  /api/market/releases            ?date=: shares coming off lock-up in the next 30 days
  GET  /api/market/lhb                 ?date=: the day's 龙虎榜 with the institutions' buying
  GET  /api/market/lhb/{code}          ?date=: that stock's top five buying and selling seats
  GET  /api/market/boards              ?date=: the day's 主板 / 创业板 / 科创板 / 北交所
  GET  /api/market/concepts            ?span=1d|5d|10d&date=: 同花顺's concept boards (latest day)
  GET  /api/market/concepts/{name}/stocks  ?date=: a concept's stocks (Eastmoney's board of that name, kept locally)
  GET  /api/market/forecasts           ?date=&period=: a report period's 业绩预告 by type and industry
  GET  /api/market/breadth/verdict     ?date=: 市场广度综合研判, each indicator judged by its own history
  GET  /api/market/breadth/structure   ?range=1d|10d|30d|60d|6m&end=: 当日市场结构 day by day
  GET  /api/market/breadth/verdict/history  ?range=&end=: that reading on each day of a span, and how it went
  GET  /api/market/breadth             ?range=&end=: 涨停溢价 and 晋级率, size styles, new highs and lows, share above MAs
  GET/POST /api/market/sync             the snapshot sync for days not on disk yet: its status, or start it
  GET  /api/etf/broad                  ?base=&range=6m|1y|all: 宽基ETF, the 20 funds' shares, 加仓指数 and its rate
  GET  /api/etf/stocks                 ?date=: what a day's share changes come to in each stock (亿元)
  GET  /api/etf/holdings/{code}        one fund's constituents: weight, quote, TTM P/E, ROE, market value
  GET  /api/market/index/{code}/members today's constituents of an index (000300: 沪深300)
  GET  /api/watchlist                   the watchlist's groups and their stocks' rows (?rows=0: groups only)
  POST /api/watchlist/groups            create a group {"name", "color"} (at most 256)
  PATCH/DELETE /api/watchlist/groups/{id}           rename / recolour, or delete a group
  PUT/DELETE /api/watchlist/groups/{id}/stocks/{code}  add an A-share to a group, or remove it
  POST /api/watchlist/groups/{id}/stocks/{code}/move   {"to": "top"|"bottom"} within the group
  PUT  /api/watchlist/notes/{code}      {"text"}: a stock's note, the same in every group
  GET  /api/stocks/search?q=            stocks by code prefix or name fragment
  GET  /api/stocks/{code}               one stock's row of the latest market table
  POST /api/runs  {"ticker", "options"}  queue an analysis of a stock code or name (options: date,
                                        analysts, research_depth, llm_provider, models, language ...)
  GET  /api/runs                        runs started since the server started
  GET  /api/runs/{id}                   a run, its agents and its sections so far
  GET  /api/runs/{id}/events            the run's events as Server-Sent Events
  GET  /api/reports                     saved reports, newest first
  GET  /api/reports/{id}                a report's sections
  GET  /api/reports/{id}/download       ?format=md|html|zip (&inline=1 to view the page)
  DELETE /api/reports/{id}              delete a report (moved to reports/.trash/, recoverable)
  GET  /api/kline/{ticker}              daily bars: ?source=snapshot for an A-share's whole history from
                                        the local store, else the last ?days= adjusted bars up to ?end=

With the front end built (``web/frontend/dist``), the server serves it too, so
``uvicorn web.server.app:app`` is the whole app. Run it on localhost: it starts
paid model runs and has no login.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from web.server import (
    breadth,
    breadth_verdict,
    concepts,
    etf_flow,
    etf_stocks,
    extras,
    market,
    reports,
    sectors,
    settings as run_settings,
    watchlist,
)
from web.server.runs import RunManager
from web.server.sync_job import SyncJob

DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
SSE_WAIT_SECONDS = 15.0


class GroupBody(BaseModel):
    name: str | None = None
    color: str | None = None


class MoveBody(BaseModel):
    to: str


class NoteBody(BaseModel):
    text: str = ""


class NewRun(BaseModel):
    ticker: str
    options: dict | None = None


def create_app(manager: RunManager | None = None, reports_root: Path | None = None,
               watchlist_path: Path | None = None, sync_job: SyncJob | None = None) -> FastAPI:
    app = FastAPI(title="TradingAgents Web", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.manager = manager or RunManager()
    sync = sync_job or SyncJob(on_done=market.invalidate)
    # The market table is ~5,000 rows of JSON; event streams are left uncompressed by default.
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    root = reports_root

    @app.get("/api/options")
    def options():
        return run_settings.options()

    @app.post("/api/runs", status_code=201)
    def start_run(body: NewRun):
        try:
            code = market.resolve_ticker(body.ticker)
            opts = run_settings.validate(body.options)
            run = app.state.manager.submit(code, opts)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        run_settings.save_prefs(opts)       # the next run, web or CLI, offers these again
        return run.summary()

    @app.get("/api/runs")
    def list_runs():
        return [r.summary() for r in app.state.manager.list()]

    def _run(run_id: str):
        run = app.state.manager.get(run_id)
        if run is None:
            raise HTTPException(404, "no such run")
        return run

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        return _run(run_id).detail()

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str, request: Request):
        run = _run(run_id)
        try:
            seq = int(request.headers.get("last-event-id") or request.query_params.get("after") or 0)
        except ValueError:
            seq = 0

        async def stream():
            nonlocal seq
            while True:
                if await request.is_disconnected():
                    return
                events = await asyncio.to_thread(app.state.manager.events_after, run, seq, SSE_WAIT_SECONDS)
                if not events:
                    if run.status in ("completed", "failed"):
                        return
                    yield ": keep-alive\n\n"
                    continue
                for e in events:
                    seq = e["seq"]
                    yield f"id: {e['seq']}\nevent: {e['type']}\ndata: {json.dumps(e['data'], ensure_ascii=False)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/market/calendar")
    def market_calendar():
        return market.calendar()

    @app.get("/api/market/stats")
    def market_stats(range: str = Query("60d"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):  # noqa: A002
        try:
            return market.market_stats(end, range)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/market/breadth/verdict")
    def market_breadth_verdict(date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        try:
            return breadth_verdict.verdict(date)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/market/breadth/structure")
    def market_breadth_structure(range: str = Query("10d"),  # noqa: A002
                                 end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        try:
            return breadth_verdict.structure_days(end, range)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/market/breadth/verdict/history")
    def market_breadth_verdict_history(range: str = Query("6m"),  # noqa: A002
                                       end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        try:
            return breadth_verdict.history(end, range)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/market/breadth")
    def market_breadth(range: str = Query("60d"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):  # noqa: A002
        try:
            return breadth.breadth(end, range)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/market/sectors")
    def market_sectors(days: int = Query(20), level: str = Query("sw1"),
                       end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        try:
            return sectors.sectors(end, days, level)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except (FileNotFoundError, LookupError) as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/market/crowding")
    def market_crowding(end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        try:
            return sectors.crowding(end)
        except (FileNotFoundError, LookupError) as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/market/valuation")
    def market_valuation(end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        try:
            return sectors.valuation(end)
        except (FileNotFoundError, LookupError) as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/market/margin")
    def market_margin(range: str = Query("1y"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):  # noqa: A002
        try:
            return extras.margin(end, range)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    def _guard(fn, *a):
        try:
            return fn(*a)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    def day_q():
        # A fresh Query for each parameter: FastAPI ties a shared one to the first name it serves.
        return Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    @app.get("/api/etf/broad")
    def etf_broad(base: str | None = day_q(), range: str = Query("1y")):  # noqa: A002
        return _guard(etf_flow.broad, base, range)

    @app.get("/api/etf/stocks")
    def etf_stocks_day(date: str | None = day_q()):
        return _guard(etf_stocks.implied, date)

    @app.get("/api/etf/holdings/{code}")
    def etf_holdings(code: str):
        return _guard(etf_stocks.holdings, code)

    @app.get("/api/market/qvix")
    def market_qvix(range: str = Query("1y"), end: str | None = day_q()):  # noqa: A002
        return _guard(extras.qvix, end, range)

    @app.get("/api/market/flow")
    def market_flow(range: str = Query("60d"), end: str | None = day_q()):  # noqa: A002
        return _guard(extras.market_flow, end, range)

    @app.get("/api/market/flow/industry")
    def market_industry_flow(span: str = Query("1d"), date: str | None = day_q()):
        return _guard(extras.industry_flow, date, span)

    @app.get("/api/market/releases")
    def market_releases(date: str | None = day_q()):
        return _guard(extras.releases, date)

    @app.get("/api/market/lhb")
    def market_lhb(date: str | None = day_q()):
        return _guard(extras.lhb, date)

    @app.get("/api/market/lhb/{code}")
    def market_lhb_seats(code: str, date: str | None = day_q()):
        if not code.isdigit() or len(code) != 6:
            raise HTTPException(400, "code must be 6 digits")
        return _guard(extras.lhb_seats, code, date)

    @app.get("/api/market/boards")
    def market_boards(date: str | None = day_q()):
        try:
            return market.boards(date)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/market/concepts")
    def market_concepts(span: str = Query("1d"), date: str | None = day_q()):
        return _guard(extras.concepts, date, span)

    @app.get("/api/market/concepts/{name}/stocks")
    def market_concept_stocks(name: str, date: str | None = day_q()):
        return _guard(concepts.board, name, date)

    @app.get("/api/market/forecasts")
    def market_forecasts(date: str | None = day_q(), period: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        return _guard(extras.forecasts, date, period)

    @app.get("/api/market/themes")
    def market_themes(days: int = Query(5), date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        try:
            return extras.themes(date, days)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/market/limits")
    def market_limits(date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        try:
            return market.limit_board(date)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/market/sync")
    def market_sync_status():
        return sync.status()

    @app.post("/api/market/sync")
    def market_sync_start():
        days = market.missing_days()
        if not days and sync.state != "running":
            return {**sync.status(), "state": "ok", "days": [], "msg": "本地行情已是最新"}
        return sync.start(days)

    @app.get("/api/market/index/{index}/members")
    def market_index_members(index: str):
        try:
            return market.index_members(index)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(502, str(e)) from e

    @app.get("/api/market/sw3")
    def market_sw3():
        """The 申万三级 set's state: built, building (n of m industries read) or failed."""
        from web.server import sw3
        return sw3.status()

    @app.post("/api/market/sw3")
    def market_sw3_download():
        """Download the 申万三级 set now, in the background (by hand)."""
        from web.server import sw3
        sw3.ensure(force=True)
        return sw3.status()

    @app.get("/api/market/sw-class")
    def market_sw_class():
        """申万's classification files kept locally: when published, checked and changed."""
        from web.server import sw_class
        return sw_class.status()

    @app.post("/api/market/sw-class/import")
    def market_sw_class_import(since: float = Query(0, ge=0)):
        """Copy the 申万 stock file the browser saved to ~/Downloads after ``since`` (epoch
        seconds) here, when it differs from the one kept; the market tables are rebuilt."""
        from web.server import sw_class
        out = sw_class.import_downloads(since)
        if out.get("changed"):
            market.industries.cache_clear()
            market.invalidate()
        return {**out, "status": sw_class.status()}

    @app.get("/api/market")
    def market_table(date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        try:
            return market.market_table(date)
        except market.NotSynced as e:
            # 409: the day is real but not on disk yet; POST /api/market/sync brings it in.
            raise HTTPException(409, {"code": "not_synced", "day": e.day, "missing": e.missing,
                                      "msg": str(e), "sync": sync.status()}) from e
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/watchlist")
    def get_watchlist(rows: bool = True):
        groups = watchlist.load(watchlist_path)
        notes = watchlist.notes(watchlist_path)
        if not rows:
            return {"groups": groups, "notes": notes, "max_groups": watchlist.MAX_GROUPS}
        try:
            w = market.watch_rows(watchlist.all_codes(groups))
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        return {"groups": groups, "notes": notes, "max_groups": watchlist.MAX_GROUPS, "date": w["date"], "flow": w["flow"],
                "ttm": w["ttm"], "rows": {r["code"]: r for r in w["rows"]}}

    def _group_call(fn, *args):
        try:
            return fn(*args, watchlist_path)
        except KeyError as e:
            raise HTTPException(404, "no such group") from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/watchlist/groups", status_code=201)
    def create_group(body: GroupBody):
        return _group_call(watchlist.create_group, body.name or "", body.color or watchlist.DEFAULT_COLOR)

    @app.patch("/api/watchlist/groups/{group_id}")
    def update_group(group_id: str, body: GroupBody):
        return _group_call(watchlist.update_group, group_id, body.name, body.color)

    @app.delete("/api/watchlist/groups/{group_id}")
    def delete_group(group_id: str):
        return {"groups": _group_call(watchlist.delete_group, group_id)}

    @app.put("/api/watchlist/groups/{group_id}/stocks/{code}")
    def add_to_group(group_id: str, code: str):
        return _group_call(watchlist.add_stock, group_id, code)

    @app.delete("/api/watchlist/groups/{group_id}/stocks/{code}")
    def remove_from_group(group_id: str, code: str):
        return _group_call(watchlist.remove_stock, group_id, code)

    @app.post("/api/watchlist/groups/{group_id}/stocks/{code}/move")
    def move_in_group(group_id: str, code: str, body: MoveBody):
        return _group_call(watchlist.move_stock, group_id, code, body.to)

    @app.put("/api/watchlist/notes/{code}")
    def set_note(code: str, body: NoteBody):
        try:
            return {"code": code, "note": watchlist.set_note(code, body.text, watchlist_path)}
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/stocks/search")
    def search_stocks(q: str = Query("", max_length=20), limit: int = Query(10, ge=1, le=50)):
        try:
            return market.search(q, limit)
        except FileNotFoundError:
            return []

    @app.get("/api/stocks/{code}")
    def stock_quote(code: str):
        try:
            row = market.quote(code)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        if row is None:
            raise HTTPException(404, f"{code} is not in the latest market snapshot")
        return row

    @app.get("/api/reports")
    def list_reports():
        return reports.list_reports(root)

    @app.get("/api/reports/{report_id}")
    def get_report(report_id: str):
        report = reports.read_report(report_id, root)
        if report is None:
            raise HTTPException(404, "no such report")
        return report

    @app.delete("/api/reports/{report_id}")
    def delete_report(report_id: str):
        where = reports.delete_report(report_id, root)
        if where is None:
            raise HTTPException(404, "no such report")
        return {"deleted": report_id, "trash": where}

    @app.get("/api/reports/{report_id}/download")
    def download(report_id: str, format: str = Query("md", pattern="^(md|html|zip)$"), inline: bool = False):
        d = reports.resolve(report_id, root)
        if d is None:
            raise HTTPException(404, "no such report")
        if format == "zip":
            data = reports.report_zip(report_id, root)
            return Response(data, media_type="application/zip",
                            headers={"Content-Disposition": f'attachment; filename="{d.name}.zip"'})
        f = d / f"complete_report.{format}"
        if not f.is_file():
            raise HTTPException(404, f"this report has no {format} file")
        media = "text/html; charset=utf-8" if format == "html" else "text/markdown; charset=utf-8"
        disposition = "inline" if inline else "attachment"
        return FileResponse(f, media_type=media, filename=f"{d.name}.{format}", content_disposition_type=disposition)

    @app.get("/api/stock/{code}/flow")
    def stock_flow(code: str):
        """The stock's main-force net inflow by day (Eastmoney, about 120 days a fetch, kept and grown on disk)."""
        from web.server import flow
        try:
            return flow.history(code)
        except LookupError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/stock/{code}/ticks")
    def stock_ticks(code: str, date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        """The day's trades one by one (成交明细), the 09:25 call-auction match included."""
        from web.server import intraday
        try:
            return intraday.ticks(code, date)
        except LookupError as e:
            raise HTTPException(404, str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, str(e)[:200]) from e

    @app.get("/api/stock/{code}/auction")
    def stock_auction(code: str):
        """The opening call auction (集合竞价, 09:15–09:25) of the latest day."""
        from web.server import intraday
        try:
            return intraday.auction(code)
        except LookupError as e:
            raise HTTPException(404, str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, str(e)[:200]) from e

    @app.get("/api/stock/{code}/intraday")
    def stock_intraday(code: str, days: int = Query(5, ge=1, le=5)):
        """The last ``days`` trading days minute by minute (五日分时), from Sina, kept a minute."""
        from web.server import intraday
        try:
            return intraday.intraday(code, days)
        except LookupError as e:
            raise HTTPException(404, str(e)) from e
        except Exception as e:  # noqa: BLE001 - the source is down or refuses
            raise HTTPException(502, f"分时数据暂不可用：{type(e).__name__}: {str(e)[:160]}") from e

    @app.get("/api/stock/{code}/rebound")
    def stock_rebound(code: str, end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        """The stock's 超跌反转 signals since listing (for the K-line markers), today's setup and
        the market condition."""
        from tradingagents.dataflows.market_context import rebound_data
        from tradingagents.dataflows.symbols import a_share_code
        c = a_share_code(code)
        if not c:
            raise HTTPException(404, "only China A-shares")
        try:
            return rebound_data(c, end)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/kline/{ticker}")
    def kline(ticker: str, end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
              days: int = Query(250, ge=20, le=2000), source: str = Query("vendor", pattern="^(vendor|snapshot)$")):
        """Daily bars. ``source=snapshot``: an A-share's whole history from the local store
        (unadjusted, since listing); otherwise, or when the store lacks the stock, the
        last ``days`` forward-adjusted bars from AKShare (A-shares) or Yahoo."""
        from tradingagents.dataflows.date_window import get_current_date
        from tradingagents.dataflows.errors import NoMarketDataError, VendorError
        from tradingagents.dataflows.symbols import a_share_code, normalize_symbol

        note = None
        if source == "snapshot" and a_share_code(ticker):
            try:
                return market.history(ticker, end)
            except FileNotFoundError as e:
                note = f"本地快照没有这只股票（{e}），改用前复权行情"
        if a_share_code(ticker):
            from tradingagents.dataflows.vendors.akshare.prices import load_ohlcv
        else:
            from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv
        try:
            df = load_ohlcv(normalize_symbol(ticker), end or get_current_date())
        except NoMarketDataError as e:
            raise HTTPException(404, str(e)) from e
        except VendorError as e:
            raise HTTPException(502, str(e)) from e
        df = df.tail(days)
        # An A-share's amount and turnover (成交额 / 换手率 panes): the same cached bars, by date.
        extra: dict = {}
        if a_share_code(ticker):
            try:
                from tradingagents.dataflows.vendors.akshare.prices import history
                h = history(normalize_symbol(ticker), end or get_current_date())
                for r in h.itertuples():
                    amt, turn = getattr(r, "Amount", None), getattr(r, "Turnover", None)
                    extra[f"{r.Date:%Y-%m-%d}"] = {"amount": float(amt) if amt == amt and amt is not None else None,
                                                   "turnover": float(turn) if turn == turn and turn is not None else None}
            except Exception:  # noqa: BLE001 - the candles stand without them
                extra = {}
        bars = [{"time": f"{r.Date:%Y-%m-%d}", "open": float(r.Open), "high": float(r.High), "low": float(r.Low),
                 "close": float(r.Close), "volume": int(r.Volume), **extra.get(f"{r.Date:%Y-%m-%d}", {})}
                for r in df.itertuples()]
        return {"symbol": normalize_symbol(ticker), "name": None, "source": "vendor",
                "adjust": "前复权" if a_share_code(ticker) else "复权", "volume_unit": "股",
                "base_through": None, "after_base": 0, "bars": bars, "note": note}

    if DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            # A file the build emitted, else the app shell: the router owns the path.
            # An unknown API path is a 404, not the page.
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404, "no such API route")
            target = (DIST / path).resolve()
            if path and target.is_file() and DIST in target.parents:
                return FileResponse(target)
            return FileResponse(DIST / "index.html")

    return app


app = create_app()
