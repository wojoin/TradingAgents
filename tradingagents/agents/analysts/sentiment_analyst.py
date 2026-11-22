"""Sentiment analyst: one sentiment report from pre-fetched sources.

The node fetches its sources before calling the model and puts them in the
prompt, so the model reports on data it was given rather than inventing posts:

  1. News headlines: the configured news vendor (Yahoo Finance by default)
  2. StockTwits messages: the cashtag stream, with Bullish/Bearish tags
  3. Reddit posts: r/wallstreetbets, r/stocks, r/investing, or crypto communities for a crypto pair

A China A-share has almost no StockTwits or Reddit coverage, so it reads AKShare
instead (``dataflows/vendors/akshare/sentiment``): 资金情绪 (fund flow, margin,
northbound holdings, 龙虎榜), 市场情绪 (limit-up pools) and 人气 (Eastmoney
popularity), alongside Eastmoney news.

Each source is trimmed to the analysis window. With a TypeSafe key, the social
posts are screened by Jev first (see post_screen). These feeds serve recent items
and are not archived, so a historical run's sentiment inputs are not
point-in-time.

The report is a SentimentReport through structured output where the provider
supports it and free text otherwise, so the band, score and confidence header
reads the same across providers. An A-share's is an AShareSentimentReport: the
same header, then each block (资金情绪, 市场情绪, 人气, 新闻) scored on its own.
"""

from datetime import datetime, timedelta

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.context import get_instrument_context_from_state, get_language_instruction
from tradingagents.agents.post_screen import jev_screen
from tradingagents.agents.schemas import (
    AShareSentimentReport,
    SentimentReport,
    render_ashare_sentiment_report,
    render_sentiment_report,
)
from tradingagents.agents.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.agents.tools import get_news
from tradingagents.dataflows.broad_etf import get_broad_etf_flow
from tradingagents.dataflows.market_context import get_market_temperature
from tradingagents.dataflows.symbols import a_share_code
from tradingagents.dataflows.vendors.akshare import sentiment as ashare_sentiment
from tradingagents.dataflows.vendors.reddit import (
    CRYPTO_SUBREDDITS,
    DEFAULT_SUBREDDITS,
    fetch_reddit_posts,
    subreddits_for,
)
from tradingagents.dataflows.vendors.stocktwits import fetch_stocktwits_messages


def _ashare_block(fetch, *args) -> str:
    """One A-share sentiment block, or a placeholder if it cannot be built at all."""
    try:
        return fetch(*args)
    except Exception as e:  # noqa: BLE001 — e.g. akshare not installed
        return f"<unavailable: {type(e).__name__}: {str(e)[:200]}>"


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def create_sentiment_analyst(llm):
    """Create a sentiment analyst node for the trading graph.

    Pre-fetches news + StockTwits + Reddit data, injects them into the
    prompt as structured blocks, and produces a deterministic sentiment
    report via structured output (with a free-text fallback for providers
    that do not support it).
    """
    structured_llm = bind_structured(llm, SentimentReport, "Sentiment Analyst")
    # An A-share's report is scored block by block (资金情绪 / 市场情绪 / 人气 / 新闻).
    ashare_structured_llm = bind_structured(llm, AShareSentimentReport, "Sentiment Analyst")

    def sentiment_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]
        start_date = _seven_days_back(end_date)
        instrument_context = get_instrument_context_from_state(state)

        # Pre-fetch all sources. Each fetcher degrades gracefully and
        # returns a string (no exceptions surface from here), so the LLM
        # always sees something — either real data or a clear placeholder.
        news_block = get_news.func(ticker, start_date, end_date)
        ashare = bool(a_share_code(ticker))
        if ashare:
            # StockTwits and Reddit carry next to nothing on A-shares; the
            # A-share read is fund flows, market-wide limit-up mood and
            # Eastmoney attention instead.
            system_message = _build_ashare_system_message(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                news_block=news_block,
                fund_block=_ashare_block(ashare_sentiment.get_fund_sentiment, ticker, end_date),
                market_block=_ashare_block(ashare_sentiment.get_market_sentiment, end_date, ticker)
                + "\n\n" + _ashare_block(get_market_temperature, end_date, ticker)
                + "\n\n" + _ashare_block(get_broad_etf_flow, end_date),
                popularity_block=_ashare_block(ashare_sentiment.get_popularity, ticker, end_date),
            )
        else:
            # Pass the analysis window so a historical run trims social posts to it
            # instead of leaking today's chatter into a backtest (#1220).
            screen = jev_screen(ticker)
            stocktwits_block = fetch_stocktwits_messages(
                ticker, limit=30, start_date=start_date, end_date=end_date, screen=screen
            )
            subreddits = subreddits_for(ticker)
            reddit_block = fetch_reddit_posts(
                ticker, subreddits, start_date=start_date, end_date=end_date, screen=screen
            )
            system_message = _build_system_message(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                news_block=news_block,
                stocktwits_block=stocktwits_block,
                reddit_block=reddit_block,
                subreddits=subreddits,
            )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Report what your tools support; another agent decides the trade."
                    # No tool-calling here: the data is pre-fetched into the
                    # prompt, so tool-range wording would only invite a
                    # hallucinated tool call (#1130).
                    " Today's date is {current_date}; treat it as 'now' for all analysis. {instrument_context}"
                    " " + NO_EXTERNAL_TOOLS +
                    "\n{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        # Format the template into a concrete message list so the structured
        # and free-text paths receive the same input. No bind_tools — the
        # data is already in the prompt.
        formatted_messages = prompt.format_messages(messages=state["messages"])

        report_text = invoke_structured_or_freetext(
            ashare_structured_llm if ashare else structured_llm,
            llm,
            formatted_messages,
            render_ashare_sentiment_report if ashare else render_sentiment_report,
            "Sentiment Analyst",
        )

        return {
            "messages": [AIMessage(content=report_text)],
            "sentiment_report": report_text,
        }

    return sentiment_analyst_node


def _build_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
    subreddits: tuple[str, ...] = DEFAULT_SUBREDDITS,
) -> str:
    """Assemble the sentiment-analyst system message with structured data blocks."""
    if subreddits == DEFAULT_SUBREDDITS:
        character = "r/wallstreetbets is often contrarian/exuberant; r/stocks more measured; r/investing longer-term"
    elif len(subreddits) > len(CRYPTO_SUBREDDITS):
        character = f"r/{subreddits[0]} leans toward the coin's holders; r/CryptoCurrency and r/CryptoMarkets are broader"
    else:
        character = "r/CryptoCurrency and r/CryptoMarkets are broad crypto communities"
    return f"""You are a financial market sentiment analyst. Your task is to produce a comprehensive sentiment report for {ticker} covering the period from {start_date} to {end_date}, drawing on three complementary data sources that have already been collected for you.

## Data sources (pre-fetched, in this prompt)

### News headlines — Yahoo Finance, past 7 days
Institutional framing. Fact-driven, slower-moving signal.

<start_of_news>
{news_block}
<end_of_news>

### StockTwits messages — retail-trader social platform indexed by cashtag
Fast-moving signal. Each message carries a user-labeled sentiment tag (Bullish / Bearish / no-label) plus the message body.

<start_of_stocktwits>
{stocktwits_block}
<end_of_stocktwits>

### Reddit posts — {", ".join(f"r/{sub}" for sub in subreddits)} (past 7 days)
Community discussion, without vote or comment counts. Subreddit character matters ({character}).

<start_of_reddit>
{reddit_block}
<end_of_reddit>

## How to analyze this data (best practices)

1. **Read the StockTwits Bullish/Bearish ratio as a leading retail-sentiment signal.** A 70/30 bullish/bearish split is moderately bullish; ≥90/10 may indicate over-extension and contrarian risk; 50/50 is uncertainty. Sample size matters — base rates on the actual message count, not percentages alone. A block headed "Screened by Jev" has had off-topic posts removed; its stance count is a classifier's read of every on-topic post fetched, labelled or not, of which the posts listed are a sample. Read it alongside the user tags.

2. **Look for cross-source divergences.** If news framing is bearish but StockTwits is overwhelmingly bullish, that mismatch is itself a signal — it can mean retail is leaning into a thesis the news flow hasn't caught up to (or vice versa, that retail is chasing while institutions are cautious).

3. **Read Reddit posts for substance.** The feed carries no vote or comment counts, so judge a post by its body excerpt, not its title alone, and do not infer engagement.

4. **Distinguish opinion from event.** A news headline ("Nvidia announces $500M Corning deal") is an event; a StockTwits post ("buying NVDA, this is going to moon") is opinion. Both are inputs but should be weighted differently in your conclusions.

5. **Identify recurring narrative themes.** What topic keeps coming up across sources? That's the dominant narrative driving current sentiment.

6. **Be honest about data limits.** If StockTwits returned only a handful of messages, or one or more sources returned an "<unavailable>" placeholder, the sentiment read is less robust — flag this explicitly in the `confidence` field and the narrative. If the sources are silent on a given subreddit, say so.

7. **Identify catalysts and risks** that emerge across sources — news of upcoming earnings, product launches, competitive threats, macro headlines, etc.

8. **Past sentiment is not predictive.** Frame your conclusions as signal for the trader to weigh alongside fundamentals and technicals, not as a price call.

## Output fields

Fill the following fields:

- **overall_band**: Exactly one of Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish. Use Mixed when sources point in clearly different directions; Neutral only when all sources are genuinely silent.
- **overall_score**: A number from 0 (maximally bearish) to 10 (maximally bullish); 5 is neutral. Keep it consistent with overall_band.
- **confidence**: low / medium / high, based on data quality and sample size.
- **narrative**: Full source-by-source breakdown, divergences, dominant narrative themes, catalysts and risks, and a markdown summary table of key sentiment signals (direction, source, supporting evidence).

{get_language_instruction()}"""


def _build_ashare_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    fund_block: str,
    market_block: str,
    popularity_block: str,
) -> str:
    """The system message for a China A-share: fund, market and attention blocks plus news."""
    return f"""You are a China A-share market sentiment analyst. Your task is to produce a sentiment report for {ticker} as of {end_date}, drawing on four blocks of data already collected for you from AKShare (Eastmoney and the exchanges). The data is in Chinese; amounts are in 亿元 (100 million yuan) unless stated.

## Data blocks (pre-fetched, in this prompt)

### Block 1 — 资金情绪 (fund sentiment): who is putting money in or taking it out
个股资金流 (main-force / extra-large / small-order net inflow), 融资融券 (margin financing balance and short-sale volume), 北向资金 (Stock Connect holdings) and 龙虎榜 (exchange-disclosed top seats on abnormal-move days).

<start_of_fund_sentiment>
{fund_block}
<end_of_fund_sentiment>

### Block 2 — 市场情绪 (market sentiment): the whole market's speculative temperature
涨停 / 炸板 / 跌停 counts, 炸板率, 最高连板 (consecutive-limit-up height), 连板梯队, and 昨日涨停今日平均涨幅 (limit-up premium), plus whether {ticker} itself sat in those pools.
Then the market's temperature as the 行情 page reads it: 情绪综合分 and its six parts (0–100) over 5 days, QVIX (implied volatility, A-shares' fear gauge) and its percentile, the margin balance with its 1 / 5 / 20-day change, 20-day slope and whether the last 5 days are speeding up or reversing (leveraged money), the policy events that changed a rule the market trades on (with whether one bears on {ticker}'s industry), the whole market's P/E percentile and equity risk premium, and the limit-up themes (主线题材) of the last 5 days with whether {ticker} was among them. Use them to judge how much risk the market is willing to take and whether {ticker}'s theme is where the speculative money is; they describe the market, not {ticker}.
Last, the 宽基ETF加仓指数: the 20 broad-based ETFs the "national team" holds, their total shares against the base day (= 100). Shares move only on creation and redemption (volume can be traded back and forth), so this is where the big money shows: a rising index with positive 5 / 20-day rates means the big money is adding, a falling one with negative rates that it is redeeming; a rate turning from negative to positive is the turn from cutting to adding. Above the upper band 70 the bottom is near (relatively close to the bottom); below the lower band 30 it is time to cut positions. Say where the index sits against its bands, which way and how fast it is moving, and what that means for the market backdrop and the timing of a position in {ticker}; it describes the whole market, not {ticker}.

<start_of_market_sentiment>
{market_block}
<end_of_market_sentiment>

### Block 3 — 人气 (retail attention): Eastmoney popularity rank and 千股千评

<start_of_popularity>
{popularity_block}
<end_of_popularity>

### Block 4 — News headlines (Eastmoney), {start_date} to {end_date}

<start_of_news>
{news_block}
<end_of_news>

## How to read A-share sentiment (best practices)

1. **Fund flow: persistence over single days.** One day of 主力净流入 means little; read the 5/10/20-day sums, the inflow-day count and the streak, and size them by 净占比 (share of turnover). 主力 inflow with 小单 outflow reads as larger money accumulating from retail; 主力 outflow with 小单 inflow reads as distribution to retail (散户接盘). The buckets are Eastmoney's tick-size estimate, not account identities, so treat them as indicative. When the block says the flow comes from 同花顺 instead, it nets every trade by buy / sell direction with no main-force or order-size split: read its sign and how it changes from 当日 to 20日, never as 主力净流入.

2. **Margin: leveraged conviction.** A rising 融资余额 means leveraged longs are adding; rising 融资余额 into a falling price is trapped leverage and a forced-selling risk; a falling balance into strength means leverage is taking profit. Rising 融券余量 is growing short interest. Margin runs through the trading day before {end_date}. A stock outside the 两融标的 list simply has no margin signal. A policy that lowers the 融资保证金比例 raises the ceiling on leveraged buying but not the willingness to use it: read the balance's response, not the announcement, and give an announced-but-not-yet-effective measure no score.

3. **Northbound: report only what is observed.** If the block says daily holdings stopped being published, say northbound positioning is unobserved; do not carry the last known figure forward as current.

4. **龙虎榜: who traded the abnormal move.** No listing is normal, not a signal. On a listing, 机构专用 net buying is the steadier money; 营业部 seats are usually short-term speculative money (游资), whose buying often reverses within days; 北向专用席位 is Stock Connect flow.

5. **Market sentiment is the backdrop, not the stock.** Many limit-ups, a low 炸板率 (under ~20%), a rising 连板 height and a positive limit-up premium mark a hot, risk-on tape that lifts speculative and small-cap names; a 炸板率 above ~40%, a shrinking height, many 跌停 and a negative premium mark money-losing, risk-off conditions. Weigh it by how speculative {ticker} is: it matters far more for a small-cap theme stock than for a large-cap blue chip. Read the trend across days, not one day.

6. **Attention: rising popularity is double-edged.** A sharply improving 人气排名 (a falling number) with a rising 新晋粉丝 share is fresh retail attention; together with 主力 outflow it is a warning of retail chasing, together with 主力 inflow it supports momentum. 千股千评 indices are Eastmoney's composites; read their direction.

7. **Look for cross-block divergences.** Fund flow against attention, the stock against the market's mood, news framing against money flow: the mismatch is itself the signal. Name the dominant narrative that recurs across blocks.

8. **Distinguish event from opinion.** A news headline or a 龙虎榜 listing is an event; a popularity rank or a composite score is a crowd read. Weigh them differently.

9. **Be honest about data limits.** Any "<... unavailable ...>" placeholder or unobserved day weakens the read; say which, and lower `confidence`. Never treat an unobserved day as an absence.

10. **Past sentiment is not predictive.** Frame conclusions as signal for the trader to weigh alongside fundamentals and technicals, not as a price call.

## Output fields

Score each block on its own first, then the whole. Fill the following fields:

- **blocks**: exactly one entry per block, in this order: 资金情绪 (Block 1), 市场情绪 (Block 2), 人气 (Block 3), 新闻 (Block 4). For each:
  - **band**: Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish, read from that block's data alone.
  - **score**: 0 (maximally bearish) to 10 (maximally bullish), 5 neutral; consistent with its band.
  - **confidence**: low / medium / high for that block alone; low when its data is unavailable, unobserved or thin, and say so rather than guess.
  - **key_evidence**: one or two sentences with the block's decisive numbers.
  市场情绪 is the whole market's mood, so score it as the backdrop it gives this stock, not as the stock's own sentiment.
- **overall_band**: Exactly one of Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish. Use Mixed when blocks point in clearly different directions; Neutral only when all blocks are genuinely silent.
- **overall_score**: 0 to 10, 5 neutral; consistent with overall_band. It is not an average of the block scores: weigh each block by its confidence and by how much it bears on this stock (market mood bears less on a large-cap blue chip than on a small-cap theme stock).
- **confidence**: low / medium / high overall, given the blocks' confidence and coverage.
- **narrative**: Organized in these sections: 资金情绪 (fund flow, margin, northbound, 龙虎榜), 市场情绪, 人气, 新闻; then cross-block divergences, the dominant narrative, catalysts and risks, and a markdown summary table of key sentiment signals (direction, block, supporting evidence).

If you answer in prose rather than these fields, open with the overall band, score and confidence, then a table with one row per block (Block | Direction | Score | Confidence | Key evidence), then the narrative.

{get_language_instruction()}"""
