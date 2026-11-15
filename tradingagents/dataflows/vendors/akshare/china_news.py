"""China news about the stock under analysis, for an A-share run's ``get_global_news``.

Only items about the stock are kept, at two levels:

  company   an item tagged with the stock (the wires tag the stocks an item is
            about) or naming it: its short name, the name without its region
            prefix (贵州茅台 -> 茅台), or its code
  industry  an item whose headline names the stock's Shenwan industry (白酒, 食品饮料)
            together with 板块 or 行业, so a headline that merely uses the word
            (电池 in an e-bike complaint) is not taken for industry news

from three sources:

  新闻联播       CCTV's evening news transcript, by date (archived by CCTV)
  财联社电报     Cailian Press's market wire
  东财快讯       Eastmoney's 7x24 wire

The two wires serve their latest items, paged back in time. Each run pages back
to where the local archive (``.akshare_data/news``) ends, at most WIRE_BACKFILL_DAYS,
and records the span it observed, so a later run, a past-dated one included, reads
the archive for any window it covers. A window the archive does not cover is
reported as unobserved, never as "no news".

Point in time: an item is served only if published by the end of the run date
(Beijing time). The stock's name and industry are today's, used only to pick items.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

import pandas as pd
import requests

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.symbols import normalize_symbol
from tradingagents.dataflows.vendors.akshare import store
from tradingagents.dataflows.vendors.akshare.prices import require_code

EXCERPT_CHARS = 160
COMPANY_ITEMS = 25        # company-level items listed per source
INDUSTRY_ITEMS = 10       # industry-level items listed per source
WIRE_BACKFILL_DAYS = 7    # how far back a run pages a wire the archive does not reach
WIRE_FRESH_SECONDS = 600  # a wire refreshed this recently is not paged again
REQUEST_TIMEOUT = 15
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

_REGIONS = (
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建", "江西",
    "山东", "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾", "内蒙古",
    "广西", "西藏", "宁夏", "新疆", "香港", "澳门", "深圳", "广州", "杭州", "南京", "武汉", "成都", "西安", "苏州",
    "厦门", "青岛", "大连", "宁波",
)
_GENERIC_INDUSTRIES = {"综合", "其他", "其它"}
_SECTOR_WORDS = re.compile("板块|行业")


# ---------------------------------------------------------------------------
# The subject: what makes an item about this stock
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Subject:
    code: str
    label: str
    names: tuple[str, ...]
    industries: tuple[str, ...]

    def _named(self, text: str) -> bool:
        # The code only as a whole number: 000002 must not match a tariff line ending in it.
        return any((re.search(rf"(?<!\d){n}(?!\d)", text) if n.isdigit() else n in text) for n in self.names)

    def level(self, title: str, body: str, codes: str = "") -> str | None:
        if self.code in codes.split(",") or self._named(title) or self._named(body):
            return "company"
        if _SECTOR_WORDS.search(title) and any(i in title for i in self.industries):
            return "industry"
        return None

    def anchor(self, text: str) -> int:
        """Where in ``text`` the stock is first named, so an excerpt shows the mention."""
        hits = [text.find(n) for n in (*self.names, *self.industries) if n in text]
        return min(hits) if hits else 0


def _name_variants(name: str, code: str) -> tuple[str, ...]:
    n = re.sub(r"\s+", "", name).replace("Ａ", "A").replace("Ｂ", "B")
    n = re.sub(r"^(\*?S?\*?ST)", "", n)
    n = re.sub(r"(?<=[一-鿿])[AB]$", "", n)
    out = [n] if n else []
    for region in _REGIONS:
        if n.startswith(region) and len(n) - len(region) >= 2:
            out.append(n[len(region):])
            break
    return tuple(dict.fromkeys([*out, code]))


def _industries(profile: dict) -> tuple[str, ...]:
    out = []
    for key in ("sw2", "sw1"):
        v = re.sub(r"(Ⅱ|Ⅲ|II|III)$", "", str(profile.get(key) or "")).strip()
        if len(v) >= 2 and v not in _GENERIC_INDUSTRIES:
            out.append(v)
    return tuple(dict.fromkeys(out))


def subject_of(ticker: str) -> Subject:
    from tradingagents.dataflows.vendors.akshare.fundamentals import local_profile

    code = require_code(ticker)
    profile = local_profile(code)
    name = re.sub(r"\s+", "", profile.get("name", ""))
    industries = _industries(profile)
    label = normalize_symbol(ticker) + (f" {name}" if name else "") + (
        f"; 申万 {' / '.join(industries)}" if industries else "")
    return Subject(code, label, _name_variants(name, code) if name else (code,), industries)


_WIRE_HEAD = re.compile(r"^【[^】]*】\s*(财联社|新华社|央视新闻)?\d*月?\d*日?电?，?")


def _excerpt(text: str, at: int = 0, n: int = EXCERPT_CHARS) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    cut = _WIRE_HEAD.match(s)            # wires repeat the headline as 【...】 and a dateline
    if cut:
        s, at = s[cut.end():], max(0, at - cut.end())
    start = max(0, at - 40) if at > n - 40 else 0
    piece = s[start:start + n]
    return ("…" if start else "") + piece + ("…" if start + n < len(s) else "")


def _levels(found: dict[str, list[str]], subject: Subject) -> str:
    if not found["company"] and not found["industry"]:
        return f"No item about {subject.label} in the observed span.\n"
    out = ""
    if found["company"]:
        out += f"Company ({len(found['company'])}):\n" + "\n".join(found["company"][:COMPANY_ITEMS]) + "\n"
        if len(found["company"]) > COMPANY_ITEMS:
            out += f"({len(found['company']) - COMPANY_ITEMS} older company items not listed)\n"
    else:
        out += "Company: no item names the stock.\n"
    if found["industry"]:
        out += f"Industry ({len(found['industry'])}):\n" + "\n".join(found["industry"][:INDUSTRY_ITEMS]) + "\n"
        if len(found["industry"]) > INDUSTRY_ITEMS:
            out += f"({len(found['industry']) - INDUSTRY_ITEMS} older industry items not listed)\n"
    return out


# ---------------------------------------------------------------------------
# 新闻联播
# ---------------------------------------------------------------------------
def _cctv_day(day: datetime) -> pd.DataFrame:
    """One evening's transcript, cached for good once the day has ended in Beijing."""
    key = f"{day:%Y%m%d}"
    path = store.root() / "news" / "cctv" / f"{key}.pkl"
    if path.exists():
        return pd.read_pickle(path)
    df = store.call(lambda: store.ak().news_cctv(date=key), "CCTV 新闻联播")
    df = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if len(df) and day.date() < store.now_cst().date():
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_pickle(path)
    return df


def _cctv(subject: Subject, start: datetime, end: datetime) -> tuple[str, int]:
    """The window's items about the stock, and how many evenings were observed."""
    found: dict[str, list[str]] = {"company": [], "industry": []}
    observed, missing = 0, []
    day = end
    while day >= start:
        try:
            df = _cctv_day(day)
        except VendorUnavailableError:
            df = None
        if df is None or df.empty:
            missing.append(f"{day:%Y-%m-%d}")
        else:
            observed += 1
            for _, r in df.iterrows():
                title, content = str(r.get("title", "")).strip(), str(r.get("content", ""))
                roundup = title.endswith("快讯")    # many briefs: judge and quote the sentence that matches
                for piece in (re.split(r"(?<=。)", content) if roundup else [content]):
                    level = subject.level(piece if roundup else title, piece)
                    if level:
                        found[level].append(f"- {day:%Y-%m-%d} **{title}**: "
                                            f"{_excerpt(piece, subject.anchor(piece))}")
                        break
        day -= timedelta(days=1)
    text = "## 新闻联播 (CCTV evening news, 19:00 Beijing time)\n" + _levels(found, subject)
    if missing:
        text += (f"Transcripts unavailable (not yet broadcast or not reachable): {', '.join(missing)}; "
                 "these days are unobserved.\n")
    return text + "\n", observed


# ---------------------------------------------------------------------------
# Live wires, archived locally
# ---------------------------------------------------------------------------
def _cls_page(cursor):
    """One page of 财联社电报 older than ``cursor`` (a unix time): (items, next cursor or None)."""
    params = {"app": "CailianpressWeb", "category": "", "last_time": int(cursor or time.time()), "os": "web",
              "refresh_type": "1", "rn": "20", "sv": "8.4.6"}
    params["sign"] = hashlib.md5(hashlib.sha1(urlencode(params).encode()).hexdigest().encode()).hexdigest()
    r = requests.get("https://www.cls.cn/v1/roll/get_roll_list", params=params, timeout=REQUEST_TIMEOUT,
                     headers={"User-Agent": USER_AGENT, "Referer": "https://www.cls.cn/telegraph"})
    r.raise_for_status()
    rows = [x for x in (r.json().get("data") or {}).get("roll_data") or [] if x.get("ctime")]
    items = [{
        "id": f"cls{x.get('id')}",
        "time": datetime.fromtimestamp(int(x["ctime"]), store.CST).replace(tzinfo=None),
        "title": str(x.get("title") or "").strip(),
        "body": str(x.get("content") or x.get("brief") or ""),
        "codes": ",".join(str(s.get("StockID", ""))[-6:] for s in x.get("stock_list") or []),
    } for x in rows]
    nxt = min((int(x["ctime"]) for x in rows), default=None)
    return items, (nxt if nxt and (cursor is None or nxt < cursor) else None)


def _em_page(cursor):
    """One page of 东财快讯 after ``cursor`` (Eastmoney's sortEnd): (items, next cursor or None)."""
    params = {"client": "web", "biz": "web_724", "fastColumn": "102", "sortEnd": cursor or "", "pageSize": "200",
              "req_trace": str(int(time.time() * 1000))}
    r = requests.get("https://np-weblist.eastmoney.com/comm/web/getFastNewsList", params=params,
                     timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    data = r.json().get("data") or {}
    rows = [x for x in data.get("fastNewsList") or [] if x.get("showTime")]
    items = [{
        "id": f"em{x.get('code')}",
        "time": pd.Timestamp(x["showTime"]).to_pydatetime(),
        "title": str(x.get("title") or "").strip(),
        "body": str(x.get("summary") or ""),
        "codes": ",".join(s.split(".")[-1] for s in x.get("stockList") or [] if re.fullmatch(r"\d+\.\d{6}", str(s))),
    } for x in rows]
    nxt = data.get("sortEnd")
    return items, (nxt if rows and nxt and nxt != cursor else None)


# name -> (title, page fetcher, page cap for a full backfill)
WIRES = {
    "cls": ("财联社电报 (Cailian Press wire)", _cls_page, 600),
    "em": ("东财快讯 (Eastmoney 7x24 wire)", _em_page, 80),
}
_COLUMNS = ["id", "time", "title", "body", "codes"]


def _paths(wire: str):
    base = store.root() / "news"
    return base / f"wire_{wire}.pkl", base / f"wire_{wire}_coverage.json"


def _load(wire: str) -> tuple[pd.DataFrame, list[list[datetime]]]:
    data, cov = _paths(wire)
    df = pd.read_pickle(data) if data.exists() else pd.DataFrame(columns=_COLUMNS)
    spans = ([[datetime.fromisoformat(a), datetime.fromisoformat(b)] for a, b in json.loads(cov.read_text())]
             if cov.exists() else [])
    return df, spans


def _merge(spans: list[list[datetime]]) -> list[list[datetime]]:
    out: list[list[datetime]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _refresh(wire: str) -> tuple[pd.DataFrame, list[list[datetime]]]:
    """Page the wire back to where the archive ends (at most WIRE_BACKFILL_DAYS) and archive what it saw."""
    df, spans = _load(wire)
    now = store.now_cst().replace(tzinfo=None)
    if spans and (now - spans[-1][1]).total_seconds() < WIRE_FRESH_SECONDS:
        return df, spans
    _, page, max_pages = WIRES[wire]
    floor = now - timedelta(days=WIRE_BACKFILL_DAYS)
    stop = max(spans[-1][1], floor) if spans else floor
    items, cursor, oldest = [], None, now
    for _ in range(max_pages):
        got, cursor = store.call(lambda c=cursor: page(c), WIRES[wire][0])
        if not got:
            break
        items += got
        oldest = min(oldest, *(x["time"] for x in got))
        if oldest <= stop or cursor is None:
            break
    if not items:
        return df, spans
    df = pd.concat([df, pd.DataFrame(items, columns=_COLUMNS)], ignore_index=True)
    df = df.drop_duplicates("id", keep="last").sort_values("time").reset_index(drop=True)
    spans = _merge([*spans, [max(oldest, stop), now]])
    data, cov = _paths(wire)
    data.parent.mkdir(parents=True, exist_ok=True)
    df.to_pickle(data)
    cov.write_text(json.dumps([[a.isoformat(), b.isoformat()] for a, b in spans]))
    return df, spans


def _wire(wire: str, subject: Subject, start: datetime, end: datetime, seen: set[str]) -> tuple[str, bool]:
    """The wire's items about the stock from ``start`` to the end of ``end``, and whether any was observed."""
    title = WIRES[wire][0]
    try:
        df, spans = _refresh(wire)
    except VendorUnavailableError as e:
        df, spans = _load(wire)
        if not spans:
            return f"## {title}\n<unavailable: {str(e)[:160]}>\n\n", False
    hi = min(end + timedelta(days=1), store.now_cst().replace(tzinfo=None))
    covered = [[max(a, start), min(b, hi)] for a, b in spans if b > start and a < hi]
    if not covered:
        return (f"## {title}\n<unavailable for {start:%Y-%m-%d}..{end:%Y-%m-%d}: the local archive does not "
                "reach this window and the wire serves only recent items, so it is unobserved>\n\n"), False
    rows = df[(df["time"] >= start) & (df["time"] < hi)].sort_values("time", ascending=False)
    found: dict[str, list[str]] = {"company": [], "industry": []}
    for _, r in rows.iterrows():
        level = subject.level(r["title"], r["body"], r["codes"])
        key = re.sub(r"\W", "", r["title"] or r["body"])[:30]
        if not level or key in seen:        # the same story often runs on both wires
            continue
        seen.add(key)
        head = f"**{r['title']}**: " if r["title"] else ""
        found[level].append(f"- {r['time']:%m-%d %H:%M} {head}{_excerpt(r['body'], subject.anchor(r['body']))}")
    span = "; ".join(f"{a:%m-%d %H:%M}–{b:%m-%d %H:%M}" for a, b in covered)
    text = f"## {title}\nObserved {span} Beijing time, {len(rows)} items scanned.\n" + _levels(found, subject)
    if covered[0][0] > start + timedelta(minutes=5):
        text += f"Before {covered[0][0]:%Y-%m-%d %H:%M} the window is unobserved (beyond the local archive).\n"
    return text + "\n", True


def get_china_news(ticker: str, as_of_date: str, look_back_days: int | None = None) -> str:
    """China news about ``ticker`` and its industry for the window ending ``as_of_date``."""
    subject = subject_of(ticker)
    if look_back_days is None:
        look_back_days = get_config()["global_news_lookback_days"]
    end = datetime.strptime(as_of_date, "%Y-%m-%d")
    start = end - timedelta(days=max(look_back_days - 1, 0))
    cctv, evenings = _cctv(subject, start, end)
    seen: set[str] = set()
    wires, observed = "", False
    for wire in WIRES:
        text, ok = _wire(wire, subject, start, end, seen)
        wires += text
        observed = observed or ok
    if not evenings and not observed:
        # Nothing was observed: the sources failed, which says nothing about the stock.
        raise VendorUnavailableError(f"AKShare China news unavailable for {start:%Y-%m-%d}..{as_of_date}")
    return (f"# China news about {subject.label}, {start:%Y-%m-%d} to {as_of_date}\n"
            f"Kept: items tagged with or naming the company ({', '.join(subject.names)}), and items whose "
            f"headline names its industry ({' / '.join(subject.industries) or 'none on record'}) "
            "together with 板块 or 行业. "
            "Items about neither are left out.\n\n" + cctv + wires)
