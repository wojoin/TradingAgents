"""The 超跌反转 rule (tradingagents/dataflows/rebound_signal.py) on synthetic bars."""
import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows import rebound_signal as rs


def _bars(closes, amounts=None):
    closes = np.asarray(closes, dtype=float)
    days = pd.bdate_range("2024-01-02", periods=len(closes)).strftime("%Y-%m-%d")
    prev = np.r_[closes[0], closes[:-1]]
    return pd.DataFrame({"date": days, "open": prev, "high": np.maximum(prev, closes) * 1.005,
                         "low": np.minimum(prev, closes) * 0.995, "close": closes,
                         "amount": amounts if amounts is not None else np.full(len(closes), 1e8),
                         "pct_chg": (closes / prev - 1) * 100})


def _slide_then_bounce():
    """80 calm days, a 25-day slide (a strong downtrend, deeply oversold), then a rebound on
    double the turnover."""
    calm = 100 + np.sin(np.arange(80) / 3)
    slide = calm[-1] * np.cumprod(np.full(25, 0.97))
    bounce = slide[-1] * np.cumprod([1.04, 1.03, 1.02, 1.01, 1.0, 1.0, 1.0, 1.0])
    closes = np.r_[calm, slide, bounce]
    amounts = np.r_[np.full(105, 1e8), np.full(8, 2e8)]
    return closes, amounts


@pytest.mark.unit
def test_a_slide_then_a_rebound_on_volume_fires_once():
    closes, amounts = _slide_then_bounce()
    sig = rs.signals(_bars(closes, amounts))
    assert len(sig) == 1                                   # the cool-down keeps one
    s = sig.iloc[0]
    day = _bars(closes, amounts)["date"].tolist().index(s["date"])
    assert 105 <= day <= 108                               # on the rebound, not during the slide
    assert s["adx"] > 25 and s["mdi"] > s["pdi"] and s["amt_ratio"] > 1
    assert s["stop"] < s["close"] and s["market_ok"] is None   # no market series given


@pytest.mark.unit
def test_without_the_volume_or_in_an_uptrend_there_is_no_signal():
    closes, amounts = _slide_then_bounce()
    assert rs.signals(_bars(closes, np.full(len(closes), 1e8))).empty      # the rebound not on more money
    rising = 100 * np.cumprod(np.full(150, 1.01)) + np.sin(np.arange(150)) # a steady climb: never oversold
    assert rs.signals(_bars(rising)).empty


@pytest.mark.unit
def test_the_market_condition_is_the_mcl_against_three_days_before():
    closes, amounts = _slide_then_bounce()
    bars = _bars(closes, amounts)
    day = rs.signals(bars).iloc[0]["date"]
    dates = bars["date"].tolist()
    i = dates.index(day)
    up = pd.Series([0.0, 0.0, 0.0, 5.0], index=dates[i - 3:i + 1])
    down = pd.Series([5.0, 0.0, 0.0, 0.0], index=dates[i - 3:i + 1])
    assert rs.signals(bars, up).iloc[0]["market_ok"] is True
    assert rs.signals(bars, down).iloc[0]["market_ok"] is False


@pytest.mark.unit
def test_an_ex_dividend_gap_is_not_read_as_a_fall():
    """Unadjusted prices halve on a 10-for-10 bonus issue; the day's change says 0%: no signal."""
    closes = np.r_[100 + np.sin(np.arange(120) / 3), 50 + np.sin(np.arange(120, 160) / 3) / 2]
    bars = _bars(closes, np.full(160, 1e8))
    bars.loc[120, "pct_chg"] = 0.0
    bars.loc[120, ["open", "high", "low"]] = [50.0, 50.3, 49.7]
    x = rs.indicators(bars)
    assert x["close_adj"].iloc[119] == pytest.approx(x["close_adj"].iloc[120], rel=0.02)
    assert rs.signals(bars).empty


def _with_after(after):
    closes, amounts = _slide_then_bounce()
    closes = np.r_[closes, closes[-1] * np.cumprod(after)]
    return _bars(closes, np.r_[amounts, np.full(len(after), 1e8)])


def _trade(bars, monkeypatch=None, sell_on=None):
    if monkeypatch is not None:
        real = rs._sell_condition
        monkeypatch.setattr(rs, "_sell_condition", lambda x: pd.Series(
            [d == sell_on for d in x["date"]], index=x.index) if sell_on else real(x) & False)
    sig = rs.signals(bars)
    return sig, rs.exits(bars, sig).iloc[0], rs.indicators(bars)


@pytest.mark.unit
def test_a_rise_to_the_take_profit_sells_at_the_target(monkeypatch):
    bars = _with_after(np.full(40, 1.02))
    sig, t, x = _trade(bars, monkeypatch)
    dates = bars["date"].tolist()
    i = dates.index(t["entry_date"])
    e = x["open_adj"][i]
    target = e * (1 + rs.TAKE_PROFIT)
    hit = next(k for k in range(i + 1, len(dates)) if bars["high"][k] * x["close_adj"][k] / bars["close"][k] >= target)
    assert t["exit"] == "盈" and t["exit_date"] == dates[hit]
    assert t["ret"] == pytest.approx(rs.TAKE_PROFIT * 100, abs=0.01)


@pytest.mark.unit
def test_a_fall_to_the_stop_loss_sells_at_the_stop(monkeypatch):
    bars = _with_after(np.r_[np.full(3, 1.0), np.full(10, 0.96), np.full(10, 1.0)])
    sig, t, x = _trade(bars, monkeypatch)
    assert t["exit"] == "止" and t["ret"] == pytest.approx(-rs.STOP_LOSS * 100, abs=0.01) and t["stop_price"] < t["entry_price"]


@pytest.mark.unit
def test_a_gap_under_the_stop_sells_at_the_open_not_the_stop(monkeypatch):
    bars = _with_after(np.r_[np.full(3, 1.0), [0.70], np.full(10, 1.0)])   # one day 30% down
    crash = len(bars) - 11
    bars.loc[crash, ["open", "high"]] = bars.loc[crash, "close"]          # it opens there: a gap under the stop
    sig, t, x = _trade(bars, monkeypatch)
    assert t["exit"] == "止" and t["ret"] < -rs.STOP_LOSS * 100


@pytest.mark.unit
def test_flat_for_120_days_sells_at_the_close_as_qi(monkeypatch):
    bars = _with_after(np.full(140, 1.0))
    sig, t, x = _trade(bars, monkeypatch)
    dates = bars["date"].tolist()
    i = dates.index(t["entry_date"])
    assert t["exit"] == "期" and t["exit_date"] == dates[i + rs.MAX_DAYS] and t["days"] == rs.MAX_DAYS


@pytest.mark.unit
def test_a_sell_signal_first_sells_at_the_next_open(monkeypatch):
    bars = _with_after(np.full(40, 1.0))
    dates = bars["date"].tolist()
    sig0 = rs.signals(bars)
    on = dates[dates.index(sig0.iloc[0]["date"]) + 5]
    sig, t, x = _trade(bars, monkeypatch, sell_on=on)
    assert t["exit"] == "卖" and t["sell_date"] == on and t["exit_date"] == dates[dates.index(on) + 1]


@pytest.mark.unit
def test_nothing_reached_yet_is_still_open(monkeypatch):
    bars = _with_after(np.full(10, 1.0))                                   # 10 days flat: no target, stop or 20 days
    sig, t, x = _trade(bars, monkeypatch)
    assert t["exit"] == "持有中" and pd.isna(t["exit_date"]) and t["target_price"] > t["entry_price"] > t["stop_price"]


@pytest.mark.unit
def test_nothing_is_sold_on_the_entry_day_t_plus_1(monkeypatch):
    bars = _with_after(np.full(30, 1.0))
    sig0 = rs.signals(bars)
    dates = bars["date"].tolist()
    entry = dates.index(sig0.iloc[0]["date"]) + 1
    bars.loc[entry, "high"] = bars.loc[entry, "close"] * 2                 # the target touched on the entry day
    sig, t, x = _trade(bars, monkeypatch)
    assert t["exit"] != "盈" or t["exit_date"] != dates[entry]


@pytest.mark.unit
def test_a_run_of_over_30_percent_in_20_days_is_a_sell_signal():
    closes = np.r_[100 + np.sin(np.arange(80) / 3), 100 * np.cumprod(np.full(25, 1.02))]   # +64% in 25 days
    bars = _bars(closes)
    sells = rs.sell_signals(bars)
    assert len(sells) >= 1
    first = sells.iloc[0]
    i = bars["date"].tolist().index(first["date"])
    assert closes[i] / closes[i - 20] > 1.3 and "20 日涨幅" in first["reason"] and first["market_weak"] is None
    # nothing while the price only drifts
    assert rs.sell_signals(_bars(100 + np.sin(np.arange(120) / 3))).empty


@pytest.mark.unit
def test_a_sell_signal_is_stronger_when_the_market_weakens():
    closes = np.r_[100 + np.sin(np.arange(80) / 3), 100 * np.cumprod(np.full(25, 1.02))]
    bars = _bars(closes)
    day = rs.sell_signals(bars).iloc[0]["date"]
    dates = bars["date"].tolist()
    i = dates.index(day)
    falling = pd.Series([5.0, 0.0, 0.0, 0.0], index=dates[i - 3:i + 1])
    rising = pd.Series([0.0, 0.0, 0.0, 5.0], index=dates[i - 3:i + 1])
    assert rs.sell_signals(bars, falling).iloc[0]["market_weak"] is True
    assert rs.sell_signals(bars, rising).iloc[0]["market_weak"] is False


@pytest.mark.unit
def test_the_peak_while_held_is_the_highest_close_between_buy_and_sale():
    bars = _with_after(np.full(40, 1.02))
    sig = rs.signals(bars)
    t = rs.exits(bars, sig).iloc[0]
    x = rs.indicators(bars)
    dates = bars["date"].tolist()
    i, k = dates.index(t["entry_date"]), dates.index(t["exit_date"])
    seg = x["close_adj"][i:k + 1]
    assert t["peak_date"] == dates[i + int(np.argmax(seg.to_numpy()))]
    assert t["peak_ret"] == pytest.approx((seg.max() / x["open_adj"][i] - 1) * 100, abs=0.01)
    assert t["peak_ret"] >= t["ret"] - 1 or t["exit"] in ("卖", "盈")
