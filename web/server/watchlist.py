"""The watchlist (自选), in named, coloured groups, with notes per stock, kept in
``~/.tradingagents/watchlist.json``:

    {"groups": [{"id": "default", "name": "默认", "color": "#2563eb", "codes": ["600519", ...]}, ...],
     "notes": {"600519": {"text": "...", "updated": "2026-11-15T06:00:00"}}}

- Up to MAX_GROUPS groups with unique names. The default group (id ``default``) always
  exists, comes first, and cannot be deleted, renamed or recoloured.
- A stock (an A-share six-digit code) may sit in several groups; each group keeps its
  own order, which a stock can be moved to the top or bottom of.
- A note belongs to the stock, not to a group: the same note shows in every group.

Stored on the server rather than in the browser, so it is the same from any browser on
this machine. A file from before groups (``{"codes": [...]}``) is read as the default group.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from tradingagents.dataflows.symbols import a_share_code

PATH = Path(os.path.expanduser("~")) / ".tradingagents" / "watchlist.json"
MAX_GROUPS = 256
NAME_MAX = 20
NOTE_MAX = 2000
DEFAULT_ID = "default"
DEFAULT_NAME = "默认"
DEFAULT_COLOR = "#2563eb"
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_LOCK = threading.Lock()


def _clean_group(g: dict) -> dict | None:
    if not isinstance(g, dict) or not isinstance(g.get("name"), str):
        return None
    codes = [c for c in g.get("codes") or [] if isinstance(c, str) and a_share_code(c) == c]
    color = g.get("color") if isinstance(g.get("color"), str) and _COLOR.match(g["color"]) else DEFAULT_COLOR
    # A group without an id (hand-edited) gets one derived from its name, so the id stays
    # the same from one read to the next until the file is written again.
    gid = str(g.get("id") or hashlib.md5(g["name"].encode()).hexdigest()[:8])
    return {"id": gid, "name": g["name"][:NAME_MAX], "color": color, "codes": list(dict.fromkeys(codes))}


def _read(path: Path | None = None) -> dict:
    """The whole file as {"groups": [...], "notes": {...}}, the default group first."""
    try:
        data = json.loads((path or PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if isinstance(data.get("groups"), list):
        groups = [g for g in (_clean_group(x) for x in data["groups"]) if g]
    elif isinstance(data.get("codes"), list):                          # before groups
        groups = [_clean_group({"id": DEFAULT_ID, "name": DEFAULT_NAME, "color": DEFAULT_COLOR,
                                "codes": data["codes"]})]
    else:
        groups = []
    default = next((g for g in groups if g["id"] == DEFAULT_ID), None)
    if default is None:
        name = DEFAULT_NAME if all(g["name"] != DEFAULT_NAME for g in groups) else f"{DEFAULT_NAME}分组"
        default = {"id": DEFAULT_ID, "name": name, "color": DEFAULT_COLOR, "codes": []}
    groups = [default, *[g for g in groups if g["id"] != DEFAULT_ID]][:MAX_GROUPS]
    notes = {}
    for code, note in (data.get("notes") or {}).items() if isinstance(data.get("notes"), dict) else []:
        if a_share_code(code) == code and isinstance(note, dict) and isinstance(note.get("text"), str) and note["text"]:
            notes[code] = {"text": note["text"][:NOTE_MAX], "updated": str(note.get("updated") or "")}
    return {"groups": groups, "notes": notes}


def _write(data: dict, path: Path | None = None) -> None:
    path = path or PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load(path: Path | None = None) -> list[dict]:
    """The groups, the default group first."""
    return _read(path)["groups"]


def notes(path: Path | None = None) -> dict[str, dict]:
    """code -> {"text", "updated"} for every stock with a note."""
    return _read(path)["notes"]


def _check_name(name: str, groups: list[dict], own_id: str | None = None) -> str:
    name = (name or "").strip()
    if not 1 <= len(name) <= NAME_MAX:
        raise ValueError(f"分组名称应为 1 到 {NAME_MAX} 个字")
    if any(g["name"] == name and g["id"] != own_id for g in groups):
        raise ValueError(f"已有名为「{name}」的分组")
    return name


def _check_color(color: str) -> str:
    if not isinstance(color, str) or not _COLOR.match(color):
        raise ValueError("颜色应为 #RRGGBB 形式，如 #e5484d")
    return color.lower()


def _find(groups: list[dict], group_id: str) -> dict:
    for g in groups:
        if g["id"] == group_id:
            return g
    raise KeyError(group_id)


def create_group(name: str, color: str = DEFAULT_COLOR, path: Path | None = None) -> dict:
    with _LOCK:
        data = _read(path)
        if len(data["groups"]) >= MAX_GROUPS:
            raise ValueError(f"最多只能有 {MAX_GROUPS} 个分组")
        group = {"id": uuid.uuid4().hex[:8], "name": _check_name(name, data["groups"]),
                 "color": _check_color(color), "codes": []}
        data["groups"].append(group)
        _write(data, path)
        return group


def update_group(group_id: str, name: str | None = None, color: str | None = None, path: Path | None = None) -> dict:
    """Rename or recolour a group; KeyError when there is no such group. The default group
    cannot be edited."""
    if group_id == DEFAULT_ID:
        raise ValueError("默认分组不可修改")
    with _LOCK:
        data = _read(path)
        g = _find(data["groups"], group_id)
        if name is not None:
            g["name"] = _check_name(name, data["groups"], group_id)
        if color is not None:
            g["color"] = _check_color(color)
        _write(data, path)
        return g


def delete_group(group_id: str, path: Path | None = None) -> list[dict]:
    if group_id == DEFAULT_ID:
        raise ValueError("默认分组不可删除")
    with _LOCK:
        data = _read(path)
        _find(data["groups"], group_id)
        data["groups"] = [g for g in data["groups"] if g["id"] != group_id]
        _write(data, path)
        return data["groups"]


def add_stock(group_id: str, code: str, path: Path | None = None) -> dict:
    """Add an A-share (any form: 600519, 600519.SH ...) to the end of a group."""
    c = a_share_code(code)
    if not c:
        raise ValueError(f"自选只支持 A 股股票：{code}")
    with _LOCK:
        data = _read(path)
        g = _find(data["groups"], group_id)
        if c not in g["codes"]:
            g["codes"].append(c)
            _write(data, path)
        return g


def remove_stock(group_id: str, code: str, path: Path | None = None) -> dict:
    c = a_share_code(code) or code
    with _LOCK:
        data = _read(path)
        g = _find(data["groups"], group_id)
        g["codes"] = [x for x in g["codes"] if x != c]
        _write(data, path)
        return g


def move_stock(group_id: str, code: str, to: str, path: Path | None = None) -> dict:
    """Move a stock to the top or bottom of a group's order."""
    if to not in ("top", "bottom"):
        raise ValueError("只能移到最前（top）或最后（bottom）")
    c = a_share_code(code) or code
    with _LOCK:
        data = _read(path)
        g = _find(data["groups"], group_id)
        if c not in g["codes"]:
            raise ValueError(f"{c} 不在这个分组里")
        rest = [x for x in g["codes"] if x != c]
        g["codes"] = [c, *rest] if to == "top" else [*rest, c]
        _write(data, path)
        return g


def set_note(code: str, text: str, path: Path | None = None) -> dict | None:
    """Set a stock's note (the same in every group); empty text deletes it."""
    c = a_share_code(code)
    if not c:
        raise ValueError(f"笔记只支持 A 股股票：{code}")
    text = (text or "").strip()
    if len(text) > NOTE_MAX:
        raise ValueError(f"笔记最多 {NOTE_MAX} 字")
    with _LOCK:
        data = _read(path)
        if text:
            data["notes"][c] = {"text": text, "updated": datetime.now().isoformat(timespec="seconds")}
        else:
            data["notes"].pop(c, None)
        _write(data, path)
        return data["notes"].get(c)


def all_codes(groups: list[dict]) -> list[str]:
    """Every watched code once, in the order first seen."""
    return list(dict.fromkeys(c for g in groups for c in g["codes"]))
