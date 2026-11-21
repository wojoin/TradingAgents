"""申万行业分类 from 申万's own files: every stock's 一级 / 二级 / 三级, kept locally.

Two files 申万宏源研究 publishes, kept under ``.akshare_data/manual/sw_class/``:

  StockClassifyUse_stock.xls   each stock's classification changes (股票代码, 计入日期, 行业代码,
                               更新日期); the latest entry per stock is its industry now
  SwClassCode_2021.xls         the 2021 standard's codes with their 一级 / 二级 / 三级 names

申万's site refuses programs (it answers them 508), so the stock file is fetched by the
browser: the 行情 page opens ``STOCK_URL``, the browser saves it to ~/Downloads, and
``import_downloads`` copies it here. A file whose classification is the same as the one on
disk is not copied; otherwise the stocks added, removed and moved are recorded in meta.json.
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
from functools import lru_cache
from pathlib import Path

import pandas as pd

from tradingagents.dataflows.vendors.akshare import store

log = logging.getLogger(__name__)
STOCK_FILE = "StockClassifyUse_stock.xls"
CODE_FILE = "SwClassCode_2021.xls"
BASE_URL = "https://www.swsresearch.com/swindex/pdf/SwClass2021/"
STOCK_URL = BASE_URL + STOCK_FILE
CODE_URL = BASE_URL + CODE_FILE
CHECK_DAYS = 30                 # the page suggests a new download once the file is this old
MAX_CHANGES = 12
_lock = threading.Lock()


def _dir() -> Path:
    return store.root() / "manual" / "sw_class"


def downloads_dir() -> Path:
    return Path.home() / "Downloads"


def _today() -> str:
    return store.now_cst().strftime("%Y-%m-%d")


def _meta() -> dict:
    try:
        return json.loads((_dir() / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_meta(meta: dict) -> None:
    _dir().mkdir(parents=True, exist_ok=True)
    (_dir() / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def _read_stock(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, dtype=str)
    if not {"股票代码", "计入日期", "行业代码"} <= set(df.columns) or len(df) < 100:
        raise ValueError(f"{path.name} 不是申万个股行业分类表")
    return df


def _read_code(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, dtype=str)
    if not {"行业代码", "一级行业名称", "二级行业名称", "三级行业名称"} <= set(df.columns):
        raise ValueError(f"{path.name} 不是申万行业代码表")
    return df


def _current(stock: pd.DataFrame) -> pd.Series:
    """code -> its 6-digit industry code now (the latest 计入日期)."""
    df = stock.assign(day=pd.to_datetime(stock["计入日期"], errors="coerce"),
                      code=stock["股票代码"].astype(str).str.extract(r"(\d{6})")[0])
    df = df.dropna(subset=["code"]).sort_values(["code", "day"])
    return df.groupby("code")["行业代码"].last().astype(str).str.strip()


def _as_of(stock: pd.DataFrame) -> str | None:
    col = "更新日期" if "更新日期" in stock else "计入日期"
    d = pd.to_datetime(stock[col], errors="coerce").max()
    return None if pd.isna(d) else d.strftime("%Y-%m-%d")


def _mtimes() -> tuple:
    return tuple((_dir() / f).stat().st_mtime if (_dir() / f).exists() else 0 for f in (STOCK_FILE, CODE_FILE))


def classes() -> pd.DataFrame:
    """code -> sw1, sw2, sw3 from the files (empty when either is missing)."""
    return _classes(str(_dir()), _mtimes())


@lru_cache(maxsize=2)
def _classes(where: str, mtimes: tuple) -> pd.DataFrame:
    empty = pd.DataFrame(columns=["sw1", "sw2", "sw3"], index=pd.Index([], name="code"))
    if not all(mtimes):
        return empty
    try:
        cur = _current(_read_stock(Path(where) / STOCK_FILE))
        code = _read_code(Path(where) / CODE_FILE)
    except Exception as e:  # noqa: BLE001 - a bad file falls back to the other sources
        log.warning("申万分类文件读取失败: %s", e)
        return empty
    names = code.assign(行业代码=code["行业代码"].astype(str).str.strip()).set_index("行业代码")
    out = pd.DataFrame({"sw1": cur.map(names["一级行业名称"]), "sw2": cur.map(names["二级行业名称"]),
                        "sw3": cur.map(names["三级行业名称"])})
    out.index.name = "code"
    return out.dropna(how="all")


def _diff(old: pd.Series, new: pd.Series) -> dict:
    added = sorted(set(new.index) - set(old.index))
    removed = sorted(set(old.index) - set(new.index))
    both = new.index.intersection(old.index)
    moved = sorted(both[new[both] != old[both]])
    return {"added": len(added), "removed": len(removed), "moved": len(moved),
            "examples": {"added": added[:10], "removed": removed[:10], "moved": moved[:10]}}


def import_file(path: Path) -> dict:
    """Copy a downloaded 申万 file here when it differs from the one kept; returns what happened."""
    path = Path(path)
    with _lock:
        _dir().mkdir(parents=True, exist_ok=True)
        if path.name.startswith("SwClassCode"):
            _read_code(path)
            shutil.copy2(path, _dir() / CODE_FILE)
            return {"file": CODE_FILE, "changed": True}
        new = _read_stock(path)
        target = _dir() / STOCK_FILE
        meta = _meta()
        meta["checked"] = _today()
        if target.exists():
            old_cur, new_cur = _current(_read_stock(target)), _current(new)
            diff = _diff(old_cur, new_cur)
            if not (diff["added"] or diff["removed"] or diff["moved"]):
                _save_meta(meta)
                return {"file": STOCK_FILE, "changed": False, "as_of": _as_of(new)}
            meta["changes"] = ([{"date": _today(), **diff}] + meta.get("changes", []))[:MAX_CHANGES]
        else:
            diff = None
        tmp = _dir() / (STOCK_FILE + ".tmp")
        shutil.copy2(path, tmp)
        tmp.replace(target)
        meta.update(updated=_today(), as_of=_as_of(new))
        _save_meta(meta)
        return {"file": STOCK_FILE, "changed": True, "as_of": meta["as_of"], "diff": diff}


def _candidates(prefix: str, since: float) -> list[Path]:
    """Files the browser saved: ``prefix.xls``, ``prefix (1).xls``, ``prefix-2.xls``…, newest first."""
    d = downloads_dir()
    files = [p for p in d.glob(f"{prefix}*.xls") if p.is_file() and p.stat().st_mtime >= since] if d.exists() else []
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def import_downloads(since: float = 0) -> dict:
    """Bring in the newest stock file (and a code table) saved to ~/Downloads after ``since``."""
    out: dict = {"found": False}
    if not (_dir() / CODE_FILE).exists():
        for p in _candidates("SwClassCode", 0):
            try:
                import_file(p)
                break
            except Exception as e:  # noqa: BLE001
                log.warning("申万代码表 %s: %s", p, e)
    for p in _candidates("StockClassifyUse_stock", since):
        try:
            out = {"found": True, "path": str(p), **import_file(p)}
            break
        except Exception as e:  # noqa: BLE001 - a half-written download: try the next
            out = {"found": False, "error": str(e)}
    return out


def status() -> dict:
    m = _meta()
    have = {f: (_dir() / f).exists() for f in (STOCK_FILE, CODE_FILE)}
    age = None
    if m.get("checked"):
        from datetime import date as Date
        age = (Date.fromisoformat(_today()) - Date.fromisoformat(m["checked"])).days
    return {"ready": all(have.values()), "stock_file": have[STOCK_FILE], "code_file": have[CODE_FILE],
            "as_of": m.get("as_of"), "checked": m.get("checked"), "updated": m.get("updated"),
            "due": age is None or age >= CHECK_DAYS, "last_change": (m.get("changes") or [None])[0],
            "stocks": len(classes()), "url": STOCK_URL, "code_url": CODE_URL,
            "dir": str(_dir()), "downloads": str(downloads_dir())}
