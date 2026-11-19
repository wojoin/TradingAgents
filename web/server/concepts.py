"""Concept boards' constituent stocks, kept locally and checked once a month.

The 行情 page lists 同花顺's concept boards. Their constituents are looked for in this order:
Eastmoney's board of the same name; 同花顺 (which shows them only behind an anti-scraping check
this app does not get round, so that step always reports itself unavailable); Sina's board of
the same name (about 170 concepts); else the reply lists why each source failed. Names match exactly, else
ignoring a trailing 「概念」, spaces, case and full-width forms. Kept under
``.akshare_data/web/concepts/``:

  names.parquet / names_sina.parquet   each source's concept boards (name, code), refreshed
                                       after CHECK_DAYS
  cons/<code>.parquet  each board's stocks (code, name); a Sina board's code is sina_<label>
  index.json          per board: when its stocks were fetched and last checked, how many, and
                      what changed at each check (stocks added and removed)

A board is read from disk when it was checked within CHECK_DAYS; older, it is fetched again
and compared, the differences recorded; never fetched, it is downloaded. When Eastmoney cannot
be reached (it rate-limits an IP that asks too often) what is on disk is used, however old.
``refresh_due`` re-checks the boards on disk that are due, a few at a time, for the manual
download (``python -m web.server.daily``).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from datetime import date as Date
from pathlib import Path

import pandas as pd

from tradingagents.dataflows.vendors.akshare import store

log = logging.getLogger(__name__)
CHECK_DAYS = 30
THS_UNAVAILABLE = "不提供可用的成分股接口（其页面数据受反爬保护）"
MAX_CHANGES = 12                 # change records kept per board
_lock = threading.Lock()


def _dir() -> Path:
    return store.root() / "web" / "concepts"


def _today() -> str:
    return store.now_cst().strftime("%Y-%m-%d")


def _age(day: str | None) -> int:
    if not day:
        return 10**6
    return (Date.fromisoformat(_today()) - Date.fromisoformat(day[:10])).days


def _load_index() -> dict:
    try:
        return json.loads((_dir() / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_index(index: dict) -> None:
    _dir().mkdir(parents=True, exist_ok=True)
    tmp = _dir() / "index.json.tmp"
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_dir() / "index.json")


def normalize(name: str) -> str:
    """A concept name for loose matching: full-width to half-width, no spaces, lower case,
    no trailing 「概念」 / 「概念股」 / 「板块」."""
    s = unicodedata.normalize("NFKC", str(name)).lower()
    s = re.sub(r"\s+", "", s)
    return re.sub(r"(概念股|概念|板块)$", "", s)


# ---------------------------------------------------------------------------
# Each source's concept boards: name -> code
# ---------------------------------------------------------------------------
SOURCES = {"em": ("names.parquet", "_names", "东方财富"), "sina": ("names_sina.parquet", "_names_sina", "新浪")}


def _em_list() -> pd.DataFrame:
    df = store.ak().stock_board_concept_name_em()
    return pd.DataFrame({"name": df["板块名称"].astype(str), "code": df["板块代码"].astype(str)})


def _sina_list() -> pd.DataFrame:
    df = store.ak().stock_sector_spot(indicator="概念")
    return pd.DataFrame({"name": df["板块"].astype(str), "code": "sina_" + df["label"].astype(str)})


def _names(source: str, fetch=None) -> pd.DataFrame:
    """A source's concept boards (name, code), from disk unless older than CHECK_DAYS."""
    file, key, label = SOURCES[source]
    path = _dir() / file
    if path.exists() and _age(_load_index().get(key, {}).get("checked")) < CHECK_DAYS:
        return pd.read_parquet(path)
    try:
        out = (fetch or (_em_list if source == "em" else _sina_list))().drop_duplicates("name")
    except Exception as e:  # noqa: BLE001 — down or rate-limited: the old list, if any
        if path.exists():
            log.info("%s concept names: %s; using the list on disk", source, e)
            return pd.read_parquet(path)
        raise LookupError(f"{label}概念板块列表不可得：{type(e).__name__}") from e
    _dir().mkdir(parents=True, exist_ok=True)
    out.to_parquet(path)
    with _lock:
        index = _load_index()
        index[key] = {"checked": _today(), "count": len(out)}
        _save_index(index)
    return out


def em_names(fetch=None) -> pd.DataFrame:
    """Eastmoney's concept boards (name, BK code)."""
    if fetch is not None:
        return _names("em", lambda: pd.DataFrame({"name": (df := fetch())["板块名称"].astype(str),
                                                  "code": df["板块代码"].astype(str)}))
    return _names("em")


def sina_names(fetch=None) -> pd.DataFrame:
    """Sina's concept boards (name, sina_<label>)."""
    if fetch is not None:
        return _names("sina", lambda: pd.DataFrame({"name": (df := fetch())["板块"].astype(str),
                                                    "code": "sina_" + df["label"].astype(str)}))
    return _names("sina")


def match(name: str, names: pd.DataFrame) -> tuple[str, str, str] | None:
    """(Eastmoney's name, its BK code, how matched: exact / loose) for a 同花顺 concept name."""
    hit = names[names["name"] == name]
    if len(hit):
        return hit["name"].iat[0], hit["code"].iat[0], "exact"
    key = normalize(name)
    loose = names[names["name"].map(normalize) == key]
    if len(loose):
        return loose["name"].iat[0], loose["code"].iat[0], "loose"
    return None


# ---------------------------------------------------------------------------
# A board's stocks
# ---------------------------------------------------------------------------
def _cons_path(code: str) -> Path:
    return _dir() / "cons" / f"{code}.parquet"


def _default_cons(code: str) -> pd.DataFrame:
    if code.startswith("sina_"):
        df = store.ak().stock_sector_detail(sector=code[len("sina_"):])
        return df.rename(columns={"code": "代码", "name": "名称"})
    return store.ak().stock_board_concept_cons_em(symbol=code)


def _fetch_cons(code: str, fetch=None) -> pd.DataFrame:
    df = (fetch or _default_cons)(code)
    if df is None or not len(df) or "代码" not in df:
        raise LookupError("empty")
    return pd.DataFrame({"code": df["代码"].astype(str).str.zfill(6), "name": df["名称"].astype(str)}).drop_duplicates("code")


def stocks(code: str, em_name: str, fetch=None, force: bool = False) -> dict:
    """A board's stocks: from disk when checked within CHECK_DAYS (unless ``force``), else from
    Eastmoney, compared with what was on disk; what is on disk when Eastmoney fails."""
    path = _cons_path(code)
    index = _load_index()
    meta = index.get(code, {})
    have = pd.read_parquet(path) if path.exists() else None
    if have is not None and not force and _age(meta.get("checked")) < CHECK_DAYS:
        return {"stocks": have, "source": "cache", "meta": meta}
    try:
        fresh = _fetch_cons(code, fetch)
    except Exception as e:  # noqa: BLE001 — Eastmoney down or rate-limited
        if have is not None:
            return {"stocks": have, "source": "stale", "meta": meta, "error": type(e).__name__}
        who = "新浪" if code.startswith("sina_") else "东方财富"
        raise LookupError(f"{who}成分股暂不可用（{type(e).__name__}，可能被临时限流），稍后再试") from e
    today = _today()
    change = None
    if have is not None:
        old, new = set(have["code"]), set(fresh["code"])
        added, removed = sorted(new - old), sorted(old - new)
        if added or removed:
            names = dict(zip(fresh["code"], fresh["name"], strict=False)) | dict(zip(have["code"], have["name"], strict=False))
            change = {"date": today, "added": [{"code": c, "name": names.get(c, c)} for c in added],
                      "removed": [{"code": c, "name": names.get(c, c)} for c in removed]}
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh.to_parquet(path)
    with _lock:
        index = _load_index()
        meta = index.get(code, {})
        meta.update({"name": em_name, "checked": today, "count": len(fresh)})
        meta.setdefault("fetched", today)
        if change:
            meta["changes"] = ([change] + meta.get("changes", []))[:MAX_CHANGES]
        index[code] = meta
        _save_index(index)
    return {"stocks": fresh, "source": "network", "meta": meta, "change": change}


def refresh_due(limit: int = 40, pause: float = 1.0, fetch=None) -> dict:
    """Re-check the boards on disk not checked for CHECK_DAYS, oldest first, at most ``limit``,
    ``pause`` seconds apart; stop at the first failure (Eastmoney rate-limits)."""
    index = _load_index()
    due = sorted((k for k, v in index.items() if not k.startswith("_") and _age(v.get("checked")) >= CHECK_DAYS),
                 key=lambda k: index[k].get("checked") or "")
    done, changed, stopped = 0, [], None
    for code in due[:limit]:
        try:
            r = stocks(code, index[code].get("name", code), fetch=fetch, force=True)
        except LookupError as e:
            stopped = str(e)
            break
        if r["source"] != "network":           # Eastmoney failed: wait for another run
            stopped = r.get("error")
            break
        done += 1
        if r.get("change"):
            changed.append({"name": index[code].get("name", code), **r["change"]})
        if pause:
            time.sleep(pause)
    return {"due": len(due), "checked": done, "changed": changed, "stopped": stopped}


def _lookup(name: str, source: str, names_fetch=None, cons_fetch=None) -> dict:
    """{"source", "em_name", "code", "matched", "r"} from one source, or {"error": why}."""
    label = SOURCES[source][2]
    try:
        names = (em_names if source == "em" else sina_names)(names_fetch)
    except LookupError as e:
        return {"error": str(e)}
    hit = match(name, names)
    if hit is None:
        return {"error": f"{label}没有与「{name}」同名的概念板块", "no_match": True}
    em_name, code, how = hit
    try:
        return {"source": source, "em_name": em_name, "code": code, "matched": how,
                "r": stocks(code, em_name, fetch=cons_fetch)}
    except LookupError as e:
        return {"error": str(e)}


def board(name: str, date: str | None = None, names_fetch=None, cons_fetch=None,
          sina_names_fetch=None, sina_cons_fetch=None) -> dict:
    """A 同花顺 concept's stocks (Eastmoney's board of the same name, else Sina's), each with its
    change, price, amount traded and 申万 industry on ``date``, the biggest risers first."""
    from web.server import market

    # Eastmoney -> 同花顺 -> Sina. 同花顺 shows its constituents only behind an anti-scraping check
    # (a cookie made by its own JavaScript), which this app does not get round: that step is
    # always unavailable, and says so.
    em = _lookup(name, "em", names_fetch, cons_fetch)
    got, why = em, None
    if "error" in em:
        sina = _lookup(name, "sina", sina_names_fetch, sina_cons_fetch)
        tried = [("东方财富", em["error"]), ("同花顺", THS_UNAVAILABLE), ("新浪", sina.get("error"))]
        if "error" in sina:
            return {"concept": name, "available": False, "tried": [{"source": a, "error": b} for a, b in tried],
                    "note": "成分股暂不可得，三个来源都不可用：" + "；".join(f"{a}：{b}" for a, b in tried)}
        got, why = sina, f"{em['error']}；同花顺：{THS_UNAVAILABLE}"
    r, em_name, code, how = got["r"], got["em_name"], got["code"], got["matched"]
    df = r["stocks"]
    day = None
    try:
        day, xs = market.cross_section(date)
        xs = xs.assign(code=xs["code"].astype(str).str.zfill(6)).drop_duplicates("code").set_index("code")
        num = lambda c: pd.to_numeric(xs[c], errors="coerce") if c in xs else pd.Series(dtype=float)  # noqa: E731
        pct, close, amount = num("pct_chg"), num("close"), num("amount")
    except Exception:  # noqa: BLE001 — the list without the day's figures
        pct = close = amount = pd.Series(dtype=float)
    sw1 = market.industries()["sw1"] if len(df) else pd.Series(dtype=object)

    def f(s: pd.Series, c: str, d: int = 2):
        v = s.get(c)
        return None if v is None or pd.isna(v) else round(float(v), d)
    rows = [{"code": c, "name": n, "pct": f(pct, c), "close": f(close, c), "amount": f(amount, c, 0),
             "industry": sw1.get(c) if isinstance(sw1.get(c), str) else None}
            for c, n in zip(df["code"], df["name"], strict=False)]
    rows.sort(key=lambda x: -(x["pct"] if x["pct"] is not None else -1e9))
    meta = r["meta"]
    traded = [x for x in rows if x["pct"] is not None]
    return {"concept": name, "em_name": em_name, "em_code": code, "matched": how, "available": True, "date": day,
            "provider": got["source"], "provider_note": why, "source": r["source"], "fetched": meta.get("fetched"), "checked": meta.get("checked"),
            "count": len(rows), "up": sum(1 for x in traded if x["pct"] > 0), "down": sum(1 for x in traded if x["pct"] < 0),
            "median": round(float(pd.Series([x["pct"] for x in traded]).median()), 2) if traded else None,
            "last_change": (meta.get("changes") or [None])[0], "stocks": rows}
