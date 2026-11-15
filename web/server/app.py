"""The web API: start an analysis from a ticker, follow it live, read and download reports.

  GET  /api/options                     what a run can be set to, defaulting to the last run's answers
  GET  /api/market                      every A-share on ?date= (latest): quote, industry, main flow
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

from web.server import market, reports, settings as run_settings
from web.server.runs import RunManager

DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
SSE_WAIT_SECONDS = 15.0


class NewRun(BaseModel):
    ticker: str
    options: dict | None = None


def create_app(manager: RunManager | None = None, reports_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="TradingAgents Web", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.manager = manager or RunManager()
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

    @app.get("/api/market")
    def market_table(date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        try:
            return market.market_table(date)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

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
        bars = [{"time": f"{r.Date:%Y-%m-%d}", "open": float(r.Open), "high": float(r.High), "low": float(r.Low),
                 "close": float(r.Close), "volume": int(r.Volume)} for r in df.itertuples()]
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
