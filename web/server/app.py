"""The web API: start an analysis from a ticker, follow it live, read and download reports.

  GET  /api/settings                    the settings a run will use (the CLI's last choices)
  POST /api/runs        {"ticker"}       queue an analysis of the ticker for today
  GET  /api/runs                        runs started since the server started
  GET  /api/runs/{id}                   a run, its agents and its sections so far
  GET  /api/runs/{id}/events            the run's events as Server-Sent Events
  GET  /api/reports                     saved reports, newest first
  GET  /api/reports/{id}                a report's sections
  GET  /api/reports/{id}/download       ?format=md|html|zip (&inline=1 to view the page)
  GET  /api/kline/{ticker}              daily bars up to ?end=, the last ?days=

With the front end built (``web/frontend/dist``), the server serves it too, so
``uvicorn web.server.app:app`` is the whole app. Run it on localhost: it starts
paid model runs and has no login.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from web.server import reports
from web.server.runs import RunManager
from web.server.settings import describe, run_config

DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
SSE_WAIT_SECONDS = 15.0


class NewRun(BaseModel):
    ticker: str


def create_app(manager: RunManager | None = None, reports_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="TradingAgents Web", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.manager = manager or RunManager()
    root = reports_root

    @app.get("/api/settings")
    def settings():
        return describe(*run_config())

    @app.post("/api/runs", status_code=201)
    def start_run(body: NewRun):
        try:
            run = app.state.manager.submit(body.ticker)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
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
    def kline(ticker: str, end: str | None = None, days: int = Query(250, ge=20, le=2000)):
        from tradingagents.dataflows.date_window import get_current_date
        from tradingagents.dataflows.errors import NoMarketDataError, VendorError
        from tradingagents.dataflows.symbols import a_share_code, normalize_symbol

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
        return {"symbol": normalize_symbol(ticker), "bars": bars}

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
