"""Policy and event calendar for the A-share market temperature.

A short, hand-kept list of measures that change a rule the market trades on: the leverage
available (两融保证金), the cost of trading (印花税), the money supply (降准降息) or who is
buying (汇金增持). Each entry records the day it was announced and the day it took effect,
because a run dated before the announcement must not see it: ``events_between`` filters on
``announced``, never on ``effective`` alone.

This is context, not a news feed. Add an entry when a measure changes something the analysts
read elsewhere in the prompt (a margin ratio, the stamp duty, the reserve requirement ratio),
not for ordinary headlines; keep the list short and material.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# How long an announced event stays in view, and how far ahead a pending effective date shows.
RECENT_DAYS = 120
UPCOMING_DAYS = 60


@dataclass(frozen=True)
class PolicyEvent:
    """One dated measure.

    ``announced`` is the day the market could first trade on the news; ``effective`` is the day
    the measure started (or starts) to apply. ``params`` are (name, before, after) triples.
    ``sectors`` are 申万一级 industry names the measure bears on most directly; empty means the
    whole market.
    """

    announced: str
    effective: str
    kind: str
    title: str
    params: tuple[tuple[str, str, str], ...] = ()
    scope: str = ""
    impact: str = ""
    sectors: tuple[str, ...] = ()


EVENTS: tuple[PolicyEvent, ...] = (
    PolicyEvent(
        announced="2023-08-27", effective="2023-08-28", kind="印花税",
        title="证券交易印花税减半征收",
        params=(("证券交易印花税", "0.1%（卖方单边）", "0.05%（卖方单边）"),),
        scope="全市场",
        impact="直接降低交易成本，利好成交活跃度与券商经纪业务",
        sectors=("非银金融",),
    ),
    PolicyEvent(
        announced="2023-09-08", effective="2023-09-11", kind="两融",
        title="沪深北交易所将融资保证金比例下限由 100% 下调至 80%",
        params=(("融资保证金比例下限", "100%", "80%"),),
        scope="全市场（沪深北）",
        impact="同额保证金可融资买入规模上限提高约 25%；同类下调的实际增量取决于赚钱效应，"
               "更多是风险偏好信号",
        sectors=("非银金融",),
    ),
    PolicyEvent(
        announced="2023-10-11", effective="2023-10-11", kind="长期资金",
        title="中央汇金增持工商银行、农业银行、中国银行、建设银行，并称拟继续增持",
        scope="四大行",
        impact="以真金白银托底，被视为类平准资金入场的信号",
        sectors=("银行",),
    ),
    PolicyEvent(
        announced="2024-09-24", effective="2024-09-24", kind="货币政策",
        title="央行降准 0.5 个百分点、下调 7 天逆回购利率并下调存量房贷利率",
        params=(("金融机构存款准备金率", "—", "-0.5pct"), ("7 天逆回购利率", "1.70%", "1.50%"),
                ("存量房贷利率", "—", "平均下调约 0.5pct")),
        scope="全市场",
        impact="一揽子宽松，带来 2024 年 9 月末的快速风险偏好抬升",
    ),
    PolicyEvent(
        announced="2024-09-26", effective="2024-09-26", kind="政治局会议",
        title="中央政治局会议提出「努力提振资本市场」",
        scope="全市场",
        impact="最高层定调，扭转市场对政策的预期",
    ),
    PolicyEvent(
        announced="2026-11-22", effective="2026-11-30", kind="两融",
        title="沪深北交易所将融资保证金比例下限由 100% 下调至 80%",
        params=(("融资保证金比例下限", "100%", "80%"),),
        scope="全市场（沪深北）",
        impact="同额保证金可融资买入规模上限提高约 25%，机构测算增量资金约 4000 亿元",
        sectors=("非银金融",),
    ),
)


def events_between(as_of: str, recent_days: int = RECENT_DAYS,
                   upcoming_days: int = UPCOMING_DAYS) -> list[PolicyEvent]:
    """The events known on ``as_of`` that are still current: announced within ``recent_days``
    before it, or taking effect within ``upcoming_days`` after it.

    An event announced after ``as_of`` is never returned: a run dated earlier could not have
    known it.
    """
    lo = (date.fromisoformat(as_of) - timedelta(days=recent_days)).isoformat()
    hi = (date.fromisoformat(as_of) + timedelta(days=upcoming_days)).isoformat()
    picked = [e for e in EVENTS if e.announced <= as_of
              and (e.announced >= lo or as_of <= e.effective <= hi)]
    return sorted(picked, key=lambda e: (e.effective, e.announced))
