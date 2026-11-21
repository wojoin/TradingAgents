"""申万三级行业: each stock's level-3 industry, kept locally and re-checked once a month.

申万宏源 publishes no level-3 constituent interface the store uses (``industry.py`` covers
levels 1 and 2), so this reads 乐咕乐股's copy through AKShare: ``sw_index_third_info`` lists
the ~336 level-3 industries, ``sw_index_third_cons`` each one's stocks (one request each).
The whole set is built in a background thread, paced, and kept under
``.akshare_data/web/sw3/``:

  members.parquet   code, sw3 (level-3 name), parent (its level-2 name as 乐咕乐股 gives it)
  meta.json         when it was last checked and last changed, how many industries were read
                    and failed, and what changed at each check (stocks added, removed, moved)

It is the fallback for 三级: 申万's own files (``sw_class``) come first, and this set is built
automatically only while they are missing. By hand: ``python -m web.server.sw3`` (through the
web server when it is up, else in this process).

Never built, or last checked more than CHECK_DAYS ago, ``ensure`` starts a check in the
background: it reads every industry again and compares with the file on disk, which is rewritten
only when stocks were added, removed or moved; the previous file stays in use meanwhile. An industry that fails keeps its stocks from the last build.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date as Date
from pathlib import Path

import pandas as pd

from tradingagents.dataflows.vendors.akshare import store

log = logging.getLogger(__name__)
CHECK_DAYS = 30
PAUSE = 0.3                      # seconds between two industries' requests
MAX_CHANGES = 12                 # change records kept
_lock = threading.Lock()
_state: dict = {"building": False, "done": 0, "total": 0, "error": None}
_cache: dict = {}


def _dir() -> Path:
    return store.root() / "web" / "sw3"


def _today() -> str:
    return store.now_cst().strftime("%Y-%m-%d")


def _meta() -> dict:
    try:
        return json.loads((_dir() / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def members() -> pd.DataFrame:
    """code -> sw3 (empty when never built); re-read when the file changes."""
    path = _dir() / "members.parquet"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        if _cache.get("mtime") is not None or "df" not in _cache:
            _cache.update(mtime=None, df=pd.DataFrame(columns=["sw3"], index=pd.Index([], name="code")))
        return _cache["df"]
    if _cache.get("mtime") != mtime:
        df = pd.read_parquet(path)
        df["code"] = df["code"].astype(str).str.zfill(6)
        _cache.update(mtime=mtime, df=df.drop_duplicates("code").set_index("code")[["sw3"]])
    return _cache["df"]


def _list() -> pd.DataFrame:
    import akshare as ak
    return ak.sw_index_third_info()


def _cons(code: str) -> pd.DataFrame:
    import akshare as ak
    return ak.sw_index_third_cons(symbol=code)


def build(list_fetch=None, cons_fetch=None, pause: float = PAUSE) -> dict:
    """Read every level-3 industry's stocks and write members.parquet; returns the meta."""
    list_fetch, cons_fetch = list_fetch or _list, cons_fetch or _cons
    table = list_fetch()
    old = members()
    _state.update(total=len(table), done=0, error=None)
    parts, failed = [], []
    for i, r in enumerate(table.itertuples(index=False)):
        code, name, parent = str(r[0]), str(r[1]), str(r[2])
        try:
            c = cons_fetch(code)
            codes = c["股票代码"].astype(str).str.extract(r"(\d{6})")[0].dropna()
            parts.append(pd.DataFrame({"code": codes, "sw3": name, "parent": parent}))
        except Exception as e:  # noqa: BLE001 - one industry failing keeps the last build's
            log.warning("sw3 %s %s: %s", code, name, e)
            failed.append(name)
            kept = old[old["sw3"] == name]
            if len(kept):
                parts.append(pd.DataFrame({"code": kept.index, "sw3": name, "parent": parent}))
        _state["done"] = i + 1
        if pause and i + 1 < len(table):
            time.sleep(pause)
    if not parts:
        raise RuntimeError("申万三级行业成分股全部获取失败")
    df = pd.concat(parts, ignore_index=True).drop_duplicates("code")
    # Compared with what is on disk: the file is rewritten only when stocks were added,
    # removed or moved to another level-3 industry; either way the check is recorded.
    new, was = df.set_index("code")["sw3"], old["sw3"]
    added = sorted(set(new.index) - set(was.index))
    removed = sorted(set(was.index) - set(new.index))
    both = new.index.intersection(was.index)
    moved = sorted(both[new[both] != was[both]])
    changed = bool(added or removed or moved) or old.empty
    prev = _meta()
    _dir().mkdir(parents=True, exist_ok=True)
    if changed:
        tmp = _dir() / "members.parquet.tmp"
        df.to_parquet(tmp, index=False)
        tmp.replace(_dir() / "members.parquet")
    today = _today()
    changes = prev.get("changes", [])
    if changed and not old.empty:
        changes = ([{"date": today, "added": len(added), "removed": len(removed), "moved": len(moved),
                     "examples": {"added": added[:10], "removed": removed[:10], "moved": moved[:10]}}]
                   + changes)[:MAX_CHANGES]
    meta = {"checked": today, "updated": today if changed else prev.get("updated", today),
            "industries": len(table), "failed": failed, "stocks": len(df), "changes": changes}
    (_dir() / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def _due() -> bool:
    m = _meta()
    checked = m.get("checked") or m.get("built")
    if not checked or not (_dir() / "members.parquet").exists():
        return True
    return (Date.fromisoformat(_today()) - Date.fromisoformat(checked)).days >= CHECK_DAYS


def _run() -> None:
    try:
        meta = build()
        log.info("sw3 built: %s", meta)
    except Exception as e:  # noqa: BLE001 - reported through status()
        log.warning("sw3 build failed: %s", e)
        _state["error"] = str(e)
    finally:
        _state["building"] = False


def ensure(force: bool = False) -> None:
    """Start a background build when the set is missing or due, or now when ``force``
    (by hand); never two at a time."""
    with _lock:
        if _state["building"]:
            return
        if not force and ((_state["error"] and not _due_retry()) or not _due()):
            return
        _state.update(building=True, error=None, failed_at=time.time())
    threading.Thread(target=_run, name="sw3-build", daemon=True).start()


def _due_retry() -> bool:
    """After a failed build, try again an hour later rather than on every page load."""
    return time.time() - _state.get("failed_at", 0) > 3600


def status() -> dict:
    m = _meta()
    return {"ready": (_dir() / "members.parquet").exists(), "building": _state["building"],
            "done": _state["done"], "total": _state["total"], "built": m.get("checked") or m.get("built"),
            "updated": m.get("updated"), "last_change": (m.get("changes") or [None])[0],
            "error": _state["error"]}


def main() -> int:
    """Download the 申万三级 set now: through the web server when it is up, else here."""
    import argparse
    import urllib.error
    import urllib.request

    ap = argparse.ArgumentParser(description="下载申万三级行业成分股")
    ap.add_argument("--server", default="http://127.0.0.1:8765")
    args = ap.parse_args()
    try:
        urllib.request.urlopen(urllib.request.Request(f"{args.server}/api/market/sw3", method="POST"), timeout=10)
    except (urllib.error.URLError, OSError):
        print("web 服务未启动，在本进程中下载……")
        meta = build()
        print(f"完成：{meta['industries']} 个三级行业、{meta['stocks']} 只股票；失败 {len(meta['failed'])} 个；"
              f"{'本地缓存已更新' if meta['updated'] == meta['checked'] else '与本地一致，未改动'}")
        return 0
    print("已交给 web 服务在后台下载，进度：")
    while True:
        with urllib.request.urlopen(f"{args.server}/api/market/sw3", timeout=10) as r:
            st = json.loads(r.read())
        print(f"\r  {st['done']}/{st['total'] or '…'}", end="", flush=True)
        if not st["building"]:
            print(f"\n{'失败：' + st['error'] if st['error'] else '完成，更新于 ' + str(st['built'])}")
            return 1 if st["error"] else 0
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
