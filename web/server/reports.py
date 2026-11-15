"""Saved reports under ``results_dir/reports``: list, read, and package for download.

A report is a directory the report writer made (``complete_report.md``, an HTML
page, and one Markdown file per agent in numbered section folders). Its id is the
directory name; an id is only ever resolved by matching a directory that exists,
so a crafted id cannot reach outside the reports folder.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.reporting import _SECTIONS

_HEADER = {
    "ticker": re.compile(r"^# Trading Analysis Report: (.+)$", re.M),
    "analysis_date": re.compile(r"^- Analysis date: (.+)$", re.M),
    "rating": re.compile(r"^- Rating: (.+)$", re.M),
    "generated": re.compile(r"^- Generated: (.+)$", re.M),
    "models": re.compile(r"^- TradingAgents [^:]+: (.+)$", re.M),
}


def reports_root() -> Path:
    return Path(DEFAULT_CONFIG["results_dir"]) / "reports"


def resolve(report_id: str, root: Path | None = None) -> Path | None:
    """The report directory named ``report_id``, or None: never a path built from the id."""
    root = root or reports_root()
    if not root.is_dir():
        return None
    for d in root.iterdir():
        if d.is_dir() and d.name == report_id and (d / "complete_report.md").is_file():
            return d
    return None


def _meta(d: Path) -> dict:
    head = (d / "complete_report.md").read_text(encoding="utf-8", errors="replace")[:4000]
    meta = {"id": d.name}
    for key, pattern in _HEADER.items():
        m = pattern.search(head)
        meta[key] = m.group(1).strip() if m else None
    if not meta["generated"]:
        meta["generated"] = datetime.fromtimestamp((d / "complete_report.md").stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S")
    meta["has_html"] = (d / "complete_report.html").is_file()
    meta["size"] = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
    return meta


def list_reports(root: Path | None = None) -> list[dict]:
    """Every saved report's metadata, newest first."""
    root = root or reports_root()
    if not root.is_dir():
        return []
    reports = [_meta(d) for d in root.iterdir() if d.is_dir() and (d / "complete_report.md").is_file()]
    return sorted(reports, key=lambda r: r["generated"] or "", reverse=True)


def read_report(report_id: str, root: Path | None = None) -> dict | None:
    """A report's metadata and its sections in report order, each agent's Markdown."""
    d = resolve(report_id, root)
    if d is None:
        return None
    sections = []
    for heading, folder, agents in _SECTIONS:
        parts = []
        for agent, filename, _path in agents:
            f = d / folder / filename
            if f.is_file():
                parts.append({"agent": agent, "file": f"{folder}/{filename}",
                              "content": f.read_text(encoding="utf-8", errors="replace")})
        if parts:
            sections.append({"heading": heading, "folder": folder, "agents": parts})
    return {**_meta(d), "sections": sections}


def report_zip(report_id: str, root: Path | None = None) -> bytes | None:
    """The whole report directory as a zip, its files under a folder named for the report."""
    d = resolve(report_id, root)
    if d is None:
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(d.rglob("*")):
            if p.is_file():
                z.write(p, f"{d.name}/{p.relative_to(d).as_posix()}")
    return buf.getvalue()
