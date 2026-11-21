from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.analysts.turn import take_turn
from tradingagents.agents.context import get_instrument_context_from_state, get_language_instruction
from tradingagents.agents.tools import (
    get_indicators,
    get_industry_context,
    get_market_breadth,
    get_rebound_signal,
    get_stock_data,
    get_verified_market_snapshot,
)

# The tools this analyst is offered; its tool node is built from the same tuple.
TOOLS = (
    get_stock_data,
    get_indicators,
    get_verified_market_snapshot,
    get_market_breadth,
    get_industry_context,
    get_rebound_signal,
)


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        system_message = (
            """You are a trading assistant tasked with analyzing financial markets. Your role is to select the **most relevant indicators** for a given market condition or trading strategy from the following list. The goal is to choose up to **8 indicators** that provide complementary insights without redundancy. Categories and each category's indicators are:

Moving Averages:
- close_50_sma: 50 SMA: A medium-term trend indicator. Usage: Identify trend direction and serve as dynamic support/resistance. Tips: It lags price; combine with faster indicators for timely signals.
- close_200_sma: 200 SMA: A long-term trend benchmark. Usage: Confirm overall market trend and identify golden/death cross setups. Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries.
- close_10_ema: 10 EMA: A responsive short-term average. Usage: Capture quick shifts in momentum and potential entry points. Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals.

MACD Related:
- macd: MACD: Computes momentum via differences of EMAs. Usage: Look for crossovers and divergence as signals of trend changes. Tips: Confirm with other indicators in low-volatility or sideways markets.
- macds: MACD Signal: An EMA smoothing of the MACD line. Usage: Use crossovers with the MACD line to trigger trades. Tips: Should be part of a broader strategy to avoid false positives.
- macdh: MACD Histogram: Shows the gap between the MACD line and its signal. Usage: Visualize momentum strength and spot divergence early. Tips: Can be volatile; complement with additional filters in fast-moving markets.

Momentum Indicators:
- rsi: RSI: Measures momentum to flag overbought/oversold conditions. Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis.

Volatility Indicators:
- boll: Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. Usage: Acts as a dynamic benchmark for price movement. Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals.
- boll_ub: Bollinger Upper Band: Typically 2 standard deviations above the middle line. Usage: Signals potential overbought conditions and breakout zones. Tips: Confirm signals with other tools; prices may ride the band in strong trends.
- boll_lb: Bollinger Lower Band: Typically 2 standard deviations below the middle line. Usage: Indicates potential oversold conditions. Tips: Use additional analysis to avoid false reversal signals.
- atr: ATR: Averages true range to measure volatility. Usage: Set stop-loss levels and adjust position sizes based on current market volatility. Tips: It's a reactive measure, so use it as part of a broader risk management strategy.

Volume-Based Indicators:
- vwma: VWMA: A moving average weighted by volume. Usage: Confirm trends by integrating price action with volume data. Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses.

- Select indicators that provide diverse and complementary information. Avoid redundancy (e.g., do not select both rsi and stochrsi). Also briefly explain why they are suitable for the given market context. When you tool call, please use the exact name of the indicators provided above as they are defined parameters, otherwise your call will fail. Please make sure to call get_stock_data first to retrieve the CSV that is needed to generate indicators. Then use get_indicators with the specific indicator names.

Before writing the final report, call get_verified_market_snapshot for this ticker and the current date, and treat it as the source of truth for any exact OHLCV, price-level, or indicator-value claim. If another tool's output conflicts with the verified snapshot, flag the discrepancy rather than inventing a reconciled number. Do not claim historical validation, support/resistance bounces, or exact percentage moves unless they are directly supported by tool output with concrete dates and prices.

For a China A-share, also call get_market_breadth for the current date (10 trading days is usually enough) to read the whole market the stock trades in: breadth (涨家占比, ADL), where the money goes (涨额占比, 额价差 / 量价差, TRIN_额 / TRIN_量: below 1 the money is with the risers), momentum (MCL), new highs and lows (净新高60), the share above the 20 / 60 / 250-day averages, limit moves and whether the market is 放量 or 缩量, the market structure (普涨, 少数股抱团, 抱团瓦解, 无差别下跌 …) and the breadth verdict. Include a short "Market backdrop" section: what the market structure is and how it is changing; always report both TRIN_额 (by amount) and TRIN_量 (by volume) for the latest day and how each moved over the days shown, side by side, never one without the other, and say whether they agree (both < 1: the money and the volume are both with the risers, a firmer reading; both > 1: both with the fallers) or diverge (e.g. TRIN_额 < 1 but TRIN_量 ≥ 1: a few large-cap risers take the money while the volume is with the fallers, a narrower, less reliable lead); and whether this stock is moving with the market or against it (e.g. one of the few risers in a 少数股抱团 market, or falling with a 无差别下跌). Treat breadth as the backdrop and a risk factor for timing, not as a signal about the stock itself, and quote its figures only from the tool output. Also call get_industry_context for the current date to place the stock among its 申万 industries and peers: whether its industry is leading or lagging the market over 5 and 20 days, and whether the stock is leading or lagging its 三级 / 二级 peers (relative strength). Add this to the "Market backdrop" section. Then call get_rebound_signal for the current date: it checks the stock against the 超跌反转 rule (the only indicator combination that beat the market in a backtest over every A-share since 2021) and lists its recent signals. Report whether the setup is in place today and any signal in the last 10 trading days (by the rule: sold all at once at +30% (盈), −15% (止), after 20 trading days (期) or on the next 卖 signal, whichever first; report the open trade's target and stop prices), and say plainly that it is a historical statistic across many stocks (a small edge, wide spread of outcomes), not a forecast for this stock. The same tool gives the backtested sell / avoid signal (a 20-day gain over 30%, or a MACD golden cross in a strong uptrend with ADX rising: both lagged the market by about 1–1.7% over the next 20 days, every year); report whether the stock is in that zone now or fired one recently, as a risk to a long position rather than a certain fall. Note also what the backtest found against common practice: a MACD death cross above zero, a close under MA20, a KDJ death cross above 80 and 放量滞涨 did not reliably precede under-performance, so do not present them as sell signals; and buying breakouts after a squeeze, pull-backs in an uptrend and MACD golden crosses in a strong uptrend all lagged the market in A-shares, so do not present those as buy signals.

Write a very detailed and nuanced report of the trends you observe. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."""
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " Report what your tools support; another agent decides the trade."
                    " You have access to the following tools: {tool_names}."
                    " Today's date is {current_date}; treat it as 'now' for all analysis and tool-call date ranges. {instrument_context}\n"
                    "{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in TOOLS]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        result, report = take_turn(prompt, llm, TOOLS, state["messages"])

        return {
            "messages": [result],
            "market_report": report,
        }

    return market_analyst_node
