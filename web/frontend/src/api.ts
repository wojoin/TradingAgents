// The server's API (web/server/app.py), typed.

export type AgentStatus = 'pending' | 'in_progress' | 'completed'
export type RunStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface RunSummary {
  id: string
  ticker: string
  symbol: string
  trade_date: string
  status: RunStatus
  created: string
  started: string | null
  finished: string | null
  report_id: string | null
  rating: string | null
  error: string | null
  options: RunOptions | null
}

export interface Choice<T = string> {
  value: T
  label: string
  help?: string
}

export interface ProviderOption {
  key: string
  label: string
  url: string | null
  url_editable: boolean
  key_env: string | null
  key_set: boolean
  models: { quick: Choice[]; deep: Choice[] }
  effort: { config_key: string; choices: Choice[] } | null
}

export interface RunOptions {
  date: string
  analysts: string[]
  research_depth: number
  llm_provider: string
  quick_think_llm: string | null
  deep_think_llm: string | null
  backend_url: string | null
  output_language: string
  effort: string | null
}

export interface Options {
  analysts: Choice[]
  depths: Choice<number>[]
  languages: Choice[]
  providers: ProviderOption[]
  defaults: RunOptions
  today: string
  prefs_found: boolean
}

export interface ReportMeta {
  id: string
  ticker: string | null
  analysis_date: string | null
  rating: string | null
  generated: string | null
  models: string | null
  has_html: boolean
  size: number
}

export interface ReportSection {
  heading: string
  folder: string
  agents: { agent: string; file: string; content: string }[]
}

export interface Report extends ReportMeta {
  sections: ReportSection[]
}

export interface Bar {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount?: number | null
  pct_chg?: number | null
  turnover?: number | null
}

export interface Kline {
  symbol: string
  name: string | null
  source: 'snapshot' | 'vendor'
  adjust: string
  volume_unit: '手' | '股'
  base_through: string | null
  after_base: number
  bars: Bar[]
  note?: string | null
}

// 五日分时: the last trading days minute by minute (Sina, unadjusted).
export interface IntradayPoint { time: string; price: number; avg: number | null; volume: number; amount: number }
export interface Intraday {
  symbol: string; prev_close: number | null; source: string; volume_unit: '股' | '手'
  days: { date: string; close: number; points: IntradayPoint[] }[]
}

// 成交明细: the day's trades one by one (shares; side 买 / 卖 / 中性, the active side).
export interface Tick { time: string; price: number; volume: number; side: string }
export interface Ticks {
  symbol: string; date: string; source: string; count: number; buy_volume: number; sell_volume: number
  auction_volume?: number; auction_count?: number   // 09:25 and 15:00 call auctions: side 竞价, neither buy nor sell
  auction: { time: string; price: number; volume: number } | null; rows: Tick[]
}
// 集合竞价 (09:15–09:25): its minutes when Eastmoney serves them, and the 09:25 match.
export interface Auction {
  symbol: string; date: string; source: string
  points: { time: string; price: number; volume: number }[]
  match: { time: string; price: number; volume: number } | null
}

// 超跌反转 (the backtested buy combination): each day it fired, and today's setup.
export interface ReboundSignal {
  date: string; trigger: string; oversold: string; adx: number | null; mdi: number | null; pdi: number | null
  amt_ratio: number | null; close: number | null; stop: number | null
  market_ok: boolean | null      // the market's MCL over its level 3 days before; null without data
  // The trade: bought at the next open, sold at the open after the first 卖 signal (sell_date) after it.
  trade: { entry_date: string | null; exit_date: string | null; sell_date: string | null
           exit: '卖' | '盈' | '止' | '期' | '持有中' | '待买入'; ret: number | null; days: number | null
           entry_price: number | null; exit_price: number | null; target_price: number | null; stop_price: number | null
           peak_date: string | null; peak_ret: number | null } | null   // the highest close while held: hindsight
  skip: string | null            // why this 反 bought nothing (grey, or a position already held); null when bought
}
export interface StockRebound {
  signals: ReboundSignal[]
  now: { date: string; downtrend: boolean; oversold: boolean; adx: number | null } | null
  market: { date: string; mcl: number | null; mcl_3d_ago: number | null; ok: boolean } | null
  market_since?: string | null
  rule: string; stats: string; note?: string
  // 卖出 / 规避: the 20-day gain over 30%, or a MACD golden cross in a strong uptrend with ADX rising.
  sells?: { date: string; reason: string; gain20: number | null; adx: number | null; close: number | null
            market_weak: boolean | null
            closes: boolean }[]          // true: the 卖 that sells a held trade; else a 规避 (avoid) signal only
  sell_rule?: string; sell_stats?: string
  // 「★ 单笔最优」: the same purple 反 entries, its own one-at-a-time book, sold at +25% / −30% /
  // 250 trading days / the next 卖, whichever first.
  best?: { rule: string; stats: string; trades: (NonNullable<ReboundSignal['trade']> & { date: string })[] }
}

export interface FlowMeta {
  source: 'eastmoney' | 'ths' | null
  label: string
  note: string
}

export interface MarketRow {
  code: string
  name: string
  exchange?: 'SH' | 'SZ' | 'BJ' | null
  pct_chg: number | null
  price: number | null
  main_flow: number | null
  open_pct: number | null
  high: number | null
  low: number | null
  amount: number | null
  volume: number | null
  pct_5d: number | null
  amplitude: number | null
  industry: string | null
  sub_industry: string | null
  industry3: string | null      // 申万三级: from 申万's files, else 乐咕乐股's copy
  industry3_src?: 'lg'          // set when it is 乐咕乐股's
  turnover: number | null
  pe_ttm: number | null
  eps_ttm: number | null
  total_mv: number | null
  total_shares: number | null
  float_mv: number | null
  float_shares: number | null
}

export interface MarketCalendar {
  min: string | null
  max: string | null
  latest: string | null
  holidays: string[]
  missing: string[]   // closed trading days after the newest snapshot: synced on demand
}

// The market day by day: rises, falls, unchanged and the amount traded (yuan).
export type StatsRange = '1d' | '60d' | '6m' | '1y'
export interface MarketDayStats {
  date: string
  up: number
  down: number
  flat: number
  total: number
  amount: number
  median: number | null     // the median stock's change (%): how most stocks did
  limit_up: number
  limit_down: number
  broken: number            // touched the upper limit, closed below it (炸板)
  amount_r5: number | null  // the amount ÷ the 5 trading days before's average (放量 > 1)
  amount_r20: number | null //   and the 20 days before's
}
export interface MarketStats {
  range: StatsRange
  start: string
  end: string
  days: MarketDayStats[]
  indexes: Record<string, { date: string; close: number }[]>   // from the day before ``start``
  index_base: string
  index_error: string | null
  note: string
}

// The day's limit moves: limit-ups by how many days in a row (连板), 炸板, limit-downs.
// 申万一级 industries over the last N trading days (the heat map) and their valuation.
export interface SectorRow {
  name: string                  // 二级: 一级-二级
  code: string
  sw1: string                   // its 申万一级 industry
  pct: (number | null)[]        // daily change (%), one per ``dates``
  cum: number | null            // compounded over the N days (%)
  cum5: number | null
  cum20: number | null
  pe: number | null
  pb: number | null
  dy: number | null             // dividend yield (%)
  pe_rank: number | null        // share of days since ``since`` at or below today's (%)
  pb_rank: number | null
  amount_share: number | null   // share of the market's amount traded (%)
}
export interface MarketSectors {
  end: string | null
  as_of: string                 // the 申万 day shown (the day picked, or the last before it)
  days: number
  level: 'sw1' | 'sw2'
  dates: string[]
  industries: SectorRow[]
  since: string
  note: string | null
}
// 行业拥挤度: each industry's turnover share and rate (5-day averages) against its own history.
export interface CrowdRow {
  name: string
  share: number | null           // today's share of the market's amount traded (%)
  share5: number | null          // its 5-day average
  share5_20d: number | null      // that average 20 trading days ago
  share_rank: number             // where share5 sits since ``since`` (%)
  turnover5: number | null       // 5-day average turnover rate (%)
  turnover_rank: number
  crowd: number                  // 拥挤度: the mean of the two ranks
  cum20: number | null           // change over 20 trading days (%)
}
export interface MarketCrowding { end: string | null; as_of: string; since: string; smooth: number; industries: CrowdRow[]; note: string | null }

export interface MarketValuation {
  end: string | null
  as_of: string
  note: string | null
  // y10: China's 10-year yield (%); erp: 股债性价比, 100 / PE less y10 (%)
  days: { date: string; pe: number | null; pb: number | null; dy: number | null; y10: number | null; erp: number | null }[]
}

// 两融余额 (Shanghai + Shenzhen), in yuan; a day is published the next morning.
export interface MarketMargin {
  range: StatsRange
  start: string
  as_of: string
  note: string | null
  days: { date: string; total: number | null; fin: number | null; fin_buy: number | null; sh: number | null; sz: number | null; chg: number | null }[]
}

// 市场广度综合研判: each breadth indicator's state judged by what followed it here.
export interface VerdictStats { days: number; up5: number | null; avg5: number | null; up20: number | null; avg20: number | null }
export interface VerdictRow {
  step: '定趋势' | '找时机' | '验真伪'
  name: string
  reading: string
  state: string | null
  lean: string                   // 偏多 / 短期偏多 / 中性 / 短期偏空 / 偏空 / 无数据
  score: number
  reason: string
  history: VerdictStats | null
}
export interface BreadthVerdict {
  date: string
  index_date: string | null
  baseline: VerdictStats
  history_from: string
  history_to: string
  rows: VerdictRow[]
  // 当日市场结构: the day's 涨家占比 / ADL, TRIN_额 / TRIN_量 and MCL together, every state with what followed it
  structure: {
    state: string | null
    readings: { up: number | null; down: number | null; flat: number | null; limit_up: number | null; limit_down: number | null;
                up_amt_pct: number | null; amt_gap: number | null; adl_day: number | null; up_pct: number | null; trin_amt: number | null; trin_vol: number | null; trin3: number | null; mcl: number | null }
    rows: (VerdictStats & { key: string; label: string; rule: string; meaning: string; today: boolean })[]
  }
  steps: Record<'trend' | 'timing' | 'check', { score: number; lean: string; text: string }>
  conclusion: { short: number; short_word: string; mid: number; mid_word: string; joint: VerdictStats; summary: string; headline: string; points: string[];
                watch: (VerdictStats & { signal: string })[]; text: string }
}

// 当日市场结构 day by day (the newest first).
export type StructureRange = '1d' | '10d' | '30d' | '60d' | '6m'
export interface StructureDay {
  date: string
  up: number | null; down: number | null; flat: number | null
  limit_up: number | null; limit_down: number | null
  up_pct: number | null; up_amt_pct: number | null; amt_gap: number | null; vol_gap: number | null
  mcl: number | null; trin_amt: number | null; trin_vol: number | null
  amount: number | null; adl_day: number | null
  structure: string | null; structure_label: string | null
}
export interface StructureDays { range: StructureRange; end: string; days: StructureDay[] }

// The reading the card would have given on each day of a span, and how the market then did.
export interface VerdictDay {
  date: string
  close: number | null           // 中证全指
  short: number; short_word: string
  mid: number; mid_word: string
  leans: Record<string, string>
  steps: Record<'定趋势' | '找时机' | '验真伪', number>
  f5: number | null              // the 中证全指 over the next 5 / 20 days (%); null until known by the span's end
  f20: number | null
}
export interface VerdictHits { days: number; right: number; rate: number | null; avg: number | null }
export interface VerdictHistory {
  range: StatsRange
  start: string
  end: string
  days: VerdictDay[]
  accuracy: Record<'short' | 'mid', { bull: VerdictHits; bear: VerdictHits; all_up: number | null }>
}

// The day's stocks by board.
export interface BoardRow {
  board: '主板' | '创业板' | '科创板' | '北交所'
  count: number
  up: number
  down: number
  flat: number
  median: number | null
  mean: number | null
  amount: number | null
  amount_share: number | null
  limit_up: number
  limit_down: number
}
export interface MarketBoards { date: string; boards: BoardRow[] }

// 同花顺's concept boards (latest day only); money in yuan, by 同花顺's measure.
export interface ConceptRow {
  name: string
  pct: number | null
  count: number | null
  inflow: number | null
  outflow: number | null
  net: number | null
  leader?: string | null
  leader_pct?: number | null
}
export interface MarketConcepts {
  date: string
  span: FlowSpan
  available: boolean
  note?: string
  count?: number
  up?: number
  net?: number | null
  concepts?: ConceptRow[]
}

// A concept's stocks: Eastmoney's board of the same name, kept locally and checked monthly.
export interface ConceptStock { code: string; name: string; pct: number | null; close: number | null; amount: number | null; industry: string | null }
export interface ConceptChange { date: string; added: { code: string; name: string }[]; removed: { code: string; name: string }[] }
export interface ConceptStocks {
  concept: string
  available: boolean
  note?: string
  em_name?: string               // the matched board's name at its source
  matched?: 'exact' | 'loose'
  provider?: 'em' | 'sina'       // Eastmoney, or Sina when Eastmoney fails or has no such board
  provider_note?: string | null  // why Sina
  tried?: { source: string; error: string | null }[]   // when none had it: each source and why
  date?: string | null
  source?: 'cache' | 'network' | 'stale'   // from disk / just fetched / Eastmoney failed, disk used
  fetched?: string
  checked?: string
  count?: number
  up?: number
  down?: number
  median?: number | null
  last_change?: ConceptChange | null
  stocks?: ConceptStock[]
}

// A report period's 业绩预告 (one a stock: the net profit attributable to shareholders).
export interface ForecastRow { code: string; name: string; type: string; chg: number | null; date: string; industry: string | null; what: string }
export interface MarketForecasts {
  date: string
  available: boolean
  note?: string
  period?: string
  periods: Record<string, number>       // period -> forecasts announced so far
  count?: number
  good?: number
  good_share?: number | null
  types?: { type: string; count: number; good: boolean }[]
  industries?: { name: string; count: number; good: number; good_share: number | null; median_chg: number | null }[]
  best?: ForecastRow[]
  latest?: ForecastRow[]
}

// QVIX: the 50ETF option volatility index (China's VIX).
export interface MarketQvix {
  range: StatsRange
  start: string
  as_of: string
  since: string
  rank: number | null            // share of days since ``since`` at or below the last close (%)
  median: number | null
  days: { date: string; close: number | null; high: number | null }[]
}
// The whole market's main-force flow (Eastmoney, the last 120 trading days), in yuan.
export interface MarketFlowDay {
  date: string
  main: number | null
  super: number | null
  large: number | null
  mid: number | null
  small: number | null
  main_pct: number | null        // of the amount traded (%)
}
export interface MarketFlow { range: StatsRange; start: string; as_of: string; first: string; days: MarketFlowDay[] }
export type FlowSpan = '1d' | '5d' | '10d'
export interface IndustryFlow {
  date: string
  span: FlowSpan
  available: boolean
  note?: string
  source?: 'eastmoney' | 'ths'   // Eastmoney's main-force flow, or 同花顺's when Eastmoney fails
  label?: string
  source_note?: string | null    // what is different about 同花顺's measure
  total?: number | null
  sw1?: { name: string; flow: number | null }[]
  sw2?: { name: string; flow: number | null }[]
}
// Shares coming off lock-up in the next 30 days.
export interface MarketReleases {
  date: string
  end: string
  total: number
  count: number
  days: { date: string; count: number; value: number | null }[]
  stocks: { code: string; name: string; date: string; kind: string; value: number | null; float_share: number | null }[]
}
// The day's 龙虎榜.
export interface LhbStock {
  code: string
  name: string
  close: number | null
  pct: number | null
  amount: number | null          // the day's amount traded (yuan)
  volume: number | null          // and volume (lots, 手)
  net: number | null             // 龙虎榜净买额
  buy: number | null
  sell: number | null
  net_share: number | null       // 净买额占总成交比 (%)
  turnover: number | null
  note: string                   // 解读
  reason: string                 // 上榜原因
  inst_buyers: number | null
  inst_sellers: number | null
  inst_net: number | null        // 机构买入净额
}
// A stock's top five buying and selling seats on its 龙虎榜 day, a set per listing reason.
export interface LhbSeat {
  seat: string
  kind: '机构' | '北向' | '营业部'
  buy: number | null
  sell: number | null
  net: number | null
  buy_share: number | null       // of the stock's amount traded that day (%)
  sell_share: number | null
}
export interface LhbSeats {
  code: string
  date: string
  available: boolean
  note?: string
  groups: { reason: string; buy: LhbSeat[]; sell: LhbSeat[]; top_buy: number | null; top_sell: number | null;
            top_net: number | null; inst_net: number | null }[]
}
export interface MarketLhb {
  date: string
  available: boolean
  note?: string
  count?: number
  net?: number | null
  inst_net?: number | null
  inst_count?: number
  stocks: LhbStock[]
}

// The limit-ups' themes (同花顺 涨停原因 split at "+"), counted on each day of ``dates``.
export interface MarketThemes {
  date: string
  dates: string[]
  have: string[]                 // the days the pool served
  themes: { name: string; today: number; counts: number[]; total: number; days_on: number; stocks: { code: string; name: string }[] }[]
}

// The market's breadth and short-term mood on each trading day (null: not enough history).
export interface BreadthDay {
  date: string
  prem_n: number | null          // yesterday's limit-ups
  prem_avg: number | null        // their average change today (%): 涨停溢价
  prem_up: number | null         // the share of them that rose today (%)
  promo_1: number | null         // 晋级率 (%): 首板 -> 2 板
  promo_2: number | null         //   2 板 -> 3 板
  promo_3: number | null         //   3 板及以上 -> higher
  promo_multi: number | null     //   every 连板 (2 板及以上) stock
  promo_all: number | null       //   every limit-up of yesterday
  nh60: number | null            // 60-day new highs / lows (count)
  nl60: number | null
  nh250: number | null           // 250-day (52-week) new highs / lows
  nl250: number | null
  ma20: number | null            // share of stocks above their 20 / 60-day MA (%)
  ma60: number | null
  height: number | null          // 空间板: the day's highest run of limit-ups
  multi_n: number | null         // stocks on a run of two or more
  mood: number | null            // 情绪综合分 0–100: the average of the six parts below
  m_updown: number | null        // 涨跌比
  m_limit: number | null         // 涨停跌停比
  m_seal: number | null          // 封板率
  m_prem: number | null          // 涨停溢价 (−5% … +5% on 0–100)
  m_promo: number | null         // 晋级率 (0 … 40%)
  m_height: number | null        // 空间板 (1 … 8 boards)
  conc100: number | null         // 成交集中度: the 100 busiest stocks' share of the amount traded (%)
  conc5pct: number | null        //   and the busiest 5% of stocks'
  amount: number | null          // the market's amount traded (yuan)
  board_主板: number | null       // each board's median change (%)
  board_创业板: number | null
  board_科创板: number | null
  board_北交所: number | null
  trin_amt: number | null        // TRIN_额: (rising ÷ falling stocks) ÷ (their amount traded ratio)
  trin_vol: number | null        // TRIN_量: the same with volume
  trin_amt10: number | null      // their 10-day averages
  trin_vol10: number | null
  trin_amt10_rank: number | null // where the 10-day averages sit among the past 250 days (%)
  trin_vol10_rank: number | null
  mcl_ratio: number | null       // (rising − falling) ÷ (rising + falling) × 1000
  mcl_osc: number | null         // McClellan oscillator: its 19-day EMA − 39-day EMA
  mcl_sum: number | null         // MSI, McClellan summation index: 19 × EMA39 − 9 × EMA19 (the oscillator summed from the start of time)
  msi_cross: number | null       // +1 / −1 on the days MSI turns positive / negative, else 0
  ma250: number | null           // share of stocks above their 250-day MA (%)
  adr: number | null             // 涨跌比: rising ÷ falling stocks
  adr10: number | null           //   its 10-day average
  adr10_rank: number | null      //   where that sits among the past 250 days (%)
  abi: number | null             // 绝对广量: |rising − falling| ÷ (rising + falling) (%)
  abi10: number | null
  thrust: number | null          // 广度推力: 10-day EMA of rising ÷ (rising + falling)
  thrust_signal: boolean | null  // a breadth thrust fired this day (from under 0.40 to over 0.615 in 10 days)
  ud_amt: number | null          // rising stocks' amount traded ÷ falling stocks'
  ud_vol: number | null          //   and volume
  up_pct: number | null          // 涨家占比: rising stocks ÷ the stocks traded (%)
  up_amt_pct: number | null      // 涨额占比: the rising stocks' share of the amount traded (%)
  up_vol_pct: number | null      // 涨量占比: their share of the volume (%)
  amt_gap: number | null         // 额价差: 涨额占比 − 涨家占比 (pp); > 0 the money is stronger than the breadth
  vol_gap: number | null         // 量价差: 涨量占比 − 涨家占比 (pp)
  net60_pct: number | null       // 净新高: (new highs − new lows) ÷ the stocks traded × 100
  net250_pct: number | null
  mcl_raw: number | null         // MCL 原始版: on the raw count (rising − falling), not ratio-adjusted
  [size: `size_${string}`]: number | null   // median change of a size band (%): size_大盘 …
}
export interface MarketBreadth {
  range: StatsRange
  start: string
  end: string
  days: BreadthDay[]
  bands: { name: string; rule: string }[]
}

export interface LimitStock {
  code: string
  name: string
  pct_chg: number | null
  close: number | null
  amount: number | null
  turnover: number | null
  industry: string | null           // Shenwan level 2 (level 1 when it has none)
  industry_l1: string | null        // Shenwan level 1
  streak?: number
  // first_time / last_time: limit-ups and limit-downs. The rest limit-ups only. shape: 一字板 (at the limit all day), T字板 (opened at it, left and came
  // back), 换手板 (rose to it). The rest from the limit-up pools, null where they lack the stock.
  shape?: '一字板' | 'T字板' | '换手板' | null
  reason?: string | null
  first_time?: string | null
  last_time?: string | null
  order_volume?: number | null      // shares
  order_amount?: number | null      // yuan
}
export interface LimitBoard {
  date: string
  limit_up: number
  limit_down: number
  broken: number
  broken_rate: number | null
  max_streak: number
  ladder: { streak: number; stocks: LimitStock[] }[]
  broken_list: LimitStock[]
  down_list: LimitStock[]
  detail_source: ('ths' | 'em')[]    // where the reasons, times and orders came from
}

// The background sync that brings the snapshots up to the last closed trading day.
export interface MarketSync {
  state: 'idle' | 'running' | 'ok' | 'error'
  days: string[]
  msg: string
  lines: string[]
  started: string | null
  finished: string | null
}

// The 409 detail of /api/market for a day not synced yet.
export interface NotSynced {
  code: 'not_synced'
  day: string
  missing: string[]
  msg: string
  sync: MarketSync
}

export interface MarketTable {
  date: string
  dates: string[]
  flow: FlowMeta
  ttm: string
  breadth: { total: number; up: number; down: number; flat: number }
  note: string | null
  count: number
  rows: MarketRow[]
  // The 申万三级 set, built in the background on first use and re-checked monthly.
  sw3?: {
    ready: boolean; building: boolean; done: number; total: number
    built: string | null       // last checked
    updated?: string | null    // last changed (the file rewritten)
    last_change?: { date: string; added: number; removed: number; moved: number } | null
    error: string | null
  }
  sw_class?: SwClassStatus
}
// 申万's own classification files kept locally (.akshare_data/manual/sw_class/).
export interface SwClassStatus {
  ready: boolean; stock_file: boolean; code_file: boolean
  as_of: string | null       // the file's latest 更新日期 (what 申万 published)
  checked: string | null     // last imported or compared
  updated: string | null     // last changed (copied)
  due: boolean               // a month since the last check
  last_change: { date: string; added: number; removed: number; moved: number } | null
  stocks: number
  url: string; code_url: string; dir: string; downloads: string
}
export interface SwClassImport {
  found: boolean; changed?: boolean; as_of?: string | null; error?: string
  diff?: { added: number; removed: number; moved: number } | null
  status: SwClassStatus
}

export interface WatchRow extends Omit<Partial<MarketRow>, "code" | "name"> {
  code: string
  name: string | null
  missing: boolean
  open_pct?: number | null
  high?: number | null
  low?: number | null
  pct_5d?: number | null
  amplitude?: number | null
  pe_ttm?: number | null
  eps_ttm?: number | null
  total_shares?: number | null
  float_mv?: number | null
  float_shares?: number | null
}

export interface WatchGroup {
  id: string
  name: string
  color: string
  codes: string[]
}

export interface StockNote {
  text: string
  updated: string
}

export interface Watchlist {
  groups: WatchGroup[]
  notes: Record<string, StockNote>
  max_groups: number
  date?: string
  flow?: FlowMeta
  ttm?: string
  rows?: Record<string, WatchRow>
}

export interface StockHit {
  code: string
  name: string
  symbol: string
}

export interface Quote extends MarketRow {
  date: string
  flow: FlowMeta
  symbol: string
}

// A failed request: the HTTP status and the body's ``detail`` (a string or an object).
// 宽基ETF: the 19 broad-based ETFs' shares (亿份), their daily change, the 加仓指数 and its rate.
export type EtfRange = '6m' | '1y' | 'all'
export interface EtfFund {
  code: string; name: string; exchange: 'SH' | 'SZ'
  shares: number; day: number | null; since_base: number; since_base_pct: number; weight: number
}
export interface EtfDay {
  date: string; total: number; change: number | null; index: number
  rate5: number | null; rate20: number | null; top: [string, number][]
}
export interface EtfBroad {
  base: string; range: EtfRange; start: string; as_of: string
  source: 'cache' | 'network' | 'stale'; note: string | null
  funds: EtfFund[]; days: EtfDay[]
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(message: string, status: number, detail: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    let detail: unknown = null
    try {
      const body = await res.json()
      detail = body?.detail ?? null
      if (typeof detail === 'string') message = detail
      else if (detail && typeof detail === 'object' && 'msg' in detail) message = String((detail as { msg: unknown }).msg)
      else if (detail) message = JSON.stringify(detail)
    } catch {
      /* not JSON */
    }
    throw new ApiError(message, res.status, detail)
  }
  return res.json() as Promise<T>
}

export const api = {
  etfBroad: (range: EtfRange, base?: string) =>
    request<EtfBroad>(`/api/etf/broad?range=${range}${base ? `&base=${base}` : ''}`),
  options: () => request<Options>('/api/options'),
  startRun: (ticker: string, options?: Partial<RunOptions>) =>
    request<RunSummary>('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker, options }),
    }),
  runs: () => request<RunSummary[]>('/api/runs'),
  reports: () => request<ReportMeta[]>('/api/reports'),
  deleteReport: (id: string) =>
    request<{ deleted: string; trash: string }>(`/api/reports/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  market: (date?: string) => request<MarketTable>(`/api/market${date ? `?date=${date}` : ''}`),
  marketSw3: () => request<NonNullable<MarketTable['sw3']>>('/api/market/sw3'),
  swClass: () => request<SwClassStatus>('/api/market/sw-class'),
  importSwClass: (since: number) => request<SwClassImport>(`/api/market/sw-class/import?since=${since}`, { method: 'POST' }),
  stockFlow: (code: string) =>
    request<{ symbol: string; since: string | null; note: string | null; days: Record<string, number> }>(
      `/api/stock/${encodeURIComponent(code)}/flow`),
  stockTicks: (code: string) => request<Ticks>(`/api/stock/${encodeURIComponent(code)}/ticks`),
  stockAuction: (code: string) => request<Auction>(`/api/stock/${encodeURIComponent(code)}/auction`),
  stockIntraday: (code: string, days = 5) =>
    request<Intraday>(`/api/stock/${encodeURIComponent(code)}/intraday?days=${days}`),
  stockRebound: (code: string, end?: string) =>
    request<StockRebound>(`/api/stock/${encodeURIComponent(code)}/rebound${end ? `?end=${end}` : ''}`),
  marketCalendar: () => request<MarketCalendar>('/api/market/calendar'),
  marketStats: (range: StatsRange, end?: string) =>
    request<MarketStats>(`/api/market/stats?range=${range}${end ? `&end=${end}` : ''}`),
  marketSectors: (days: number, end?: string, level: 'sw1' | 'sw2' = 'sw1') =>
    request<MarketSectors>(`/api/market/sectors?days=${days}&level=${level}${end ? `&end=${end}` : ''}`),
  marketCrowding: (end?: string) => request<MarketCrowding>(`/api/market/crowding${end ? `?end=${end}` : ''}`),
  marketValuation: (end?: string) => request<MarketValuation>(`/api/market/valuation${end ? `?end=${end}` : ''}`),
  marketMargin: (range: StatsRange, end?: string) =>
    request<MarketMargin>(`/api/market/margin?range=${range}${end ? `&end=${end}` : ''}`),
  breadthStructure: (range: StructureRange, end?: string) =>
    request<StructureDays>(`/api/market/breadth/structure?range=${range}${end ? `&end=${end}` : ''}`),
  breadthVerdictHistory: (range: StatsRange, end?: string) =>
    request<VerdictHistory>(`/api/market/breadth/verdict/history?range=${range}${end ? `&end=${end}` : ''}`),
  breadthVerdict: (date?: string) => request<BreadthVerdict>(`/api/market/breadth/verdict${date ? `?date=${date}` : ''}`),
  marketBoards: (date?: string) => request<MarketBoards>(`/api/market/boards${date ? `?date=${date}` : ''}`),
  marketConcepts: (span: FlowSpan, date?: string) =>
    request<MarketConcepts>(`/api/market/concepts?span=${span}${date ? `&date=${date}` : ''}`),
  marketConceptStocks: (name: string, date?: string) =>
    request<ConceptStocks>(`/api/market/concepts/${encodeURIComponent(name)}/stocks${date ? `?date=${date}` : ''}`),
  marketForecasts: (date?: string, period?: string) =>
    request<MarketForecasts>(`/api/market/forecasts?${new URLSearchParams({ ...(date ? { date } : {}), ...(period ? { period } : {}) })}`),
  marketQvix: (range: StatsRange, end?: string) =>
    request<MarketQvix>(`/api/market/qvix?range=${range}${end ? `&end=${end}` : ''}`),
  marketFlow: (range: StatsRange, end?: string) =>
    request<MarketFlow>(`/api/market/flow?range=${range}${end ? `&end=${end}` : ''}`),
  industryFlow: (span: FlowSpan, date?: string) =>
    request<IndustryFlow>(`/api/market/flow/industry?span=${span}${date ? `&date=${date}` : ''}`),
  marketReleases: (date?: string) => request<MarketReleases>(`/api/market/releases${date ? `?date=${date}` : ''}`),
  marketLhbSeats: (code: string, date?: string) =>
    request<LhbSeats>(`/api/market/lhb/${code}${date ? `?date=${date}` : ''}`),
  marketLhb: (date?: string) => request<MarketLhb>(`/api/market/lhb${date ? `?date=${date}` : ''}`),
  marketThemes: (days: number, date?: string) =>
    request<MarketThemes>(`/api/market/themes?days=${days}${date ? `&date=${date}` : ''}`),
  marketBreadth: (range: StatsRange, end?: string) =>
    request<MarketBreadth>(`/api/market/breadth?range=${range}${end ? `&end=${end}` : ''}`),
  marketLimits: (date?: string) => request<LimitBoard>(`/api/market/limits${date ? `?date=${date}` : ''}`),
  marketSync: () => request<MarketSync>('/api/market/sync'),
  startMarketSync: () => request<MarketSync>('/api/market/sync', { method: 'POST' }),
  indexMembers: (index: string) =>
    request<{ index: string; name: string; as_of: string | null; codes: string[] }>(`/api/market/index/${index}/members`),
  search: (q: string, limit = 10) =>
    request<StockHit[]>(`/api/stocks/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  quote: (code: string) => request<Quote>(`/api/stocks/${encodeURIComponent(code)}`),
  watchlist: (rows = true) => request<Watchlist>(`/api/watchlist${rows ? '' : '?rows=0'}`),
  createGroup: (name: string, color: string) =>
    request<WatchGroup>('/api/watchlist/groups', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, color }),
    }),
  updateGroup: (id: string, patch: { name?: string; color?: string }) =>
    request<WatchGroup>(`/api/watchlist/groups/${encodeURIComponent(id)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
    }),
  deleteGroup: (id: string) =>
    request<{ groups: WatchGroup[] }>(`/api/watchlist/groups/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  addToGroup: (id: string, code: string) =>
    request<WatchGroup>(`/api/watchlist/groups/${encodeURIComponent(id)}/stocks/${encodeURIComponent(code)}`, { method: 'PUT' }),
  moveInGroup: (id: string, code: string, to: 'top' | 'bottom') =>
    request<WatchGroup>(`/api/watchlist/groups/${encodeURIComponent(id)}/stocks/${encodeURIComponent(code)}/move`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to }),
    }),
  setNote: (code: string, text: string) =>
    request<{ code: string; note: StockNote | null }>(`/api/watchlist/notes/${encodeURIComponent(code)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }),
    }),
  removeFromGroup: (id: string, code: string) =>
    request<WatchGroup>(`/api/watchlist/groups/${encodeURIComponent(id)}/stocks/${encodeURIComponent(code)}`, { method: 'DELETE' }),
  report: (id: string) => request<Report>(`/api/reports/${encodeURIComponent(id)}`),
  // source 'snapshot': an A-share's whole history from the local store (unadjusted).
  kline: (ticker: string, end?: string, days = 250, source: 'vendor' | 'snapshot' = 'vendor') => {
    const q = new URLSearchParams({ days: String(days), source })
    if (end) q.set('end', end)
    return request<Kline>(`/api/kline/${encodeURIComponent(ticker)}?${q}`)
  },
  download: (id: string, format: 'md' | 'html' | 'zip', inline = false) =>
    `/api/reports/${encodeURIComponent(id)}/download?format=${format}${inline ? '&inline=1' : ''}`,
  events: (runId: string) => new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`),
}

export const AGENT_LABELS: Record<string, string> = {
  'Market Analyst': '市场分析师',
  'Sentiment Analyst': '情绪分析师',
  'News Analyst': '新闻分析师',
  'Fundamentals Analyst': '基本面分析师',
  'Bull Researcher': '多头研究员',
  'Bear Researcher': '空头研究员',
  'Research Manager': '研究经理',
  Trader: '交易员',
  'Aggressive Analyst': '激进风控',
  'Conservative Analyst': '保守风控',
  'Neutral Analyst': '中性风控',
  'Portfolio Manager': '投资组合经理',
}

export const RUN_STATUS: Record<RunStatus, { label: string; severity: string }> = {
  queued: { label: '排队中', severity: 'secondary' },
  running: { label: '分析中', severity: 'info' },
  completed: { label: '已完成', severity: 'success' },
  failed: { label: '失败', severity: 'danger' },
}

// Bullish ratings read green-for-buy in most UIs, but A-share convention is red for up:
// colour by direction with red = positive, green = negative.
export function ratingSeverity(rating: string | null | undefined): string {
  const r = (rating || '').toLowerCase()
  if (r.includes('overweight') || r === 'buy') return 'danger'
  if (r.includes('underweight') || r === 'sell') return 'success'
  if (r.includes('hold')) return 'warn'
  return 'secondary'
}

export function formatSize(bytes: number): string {
  return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`
}

// Amounts in yuan as 亿 / 万, signed when asked.
export function formatYuan(v: number | null | undefined, signed = false): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const sign = signed && v > 0 ? '+' : ''
  const a = Math.abs(v)
  if (a >= 1e8) return `${sign}${(v / 1e8).toFixed(2)}亿`
  if (a >= 1e4) return `${sign}${(v / 1e4).toFixed(0)}万`
  return `${sign}${v.toFixed(0)}`
}

// Volume in lots (手) as 万手.
export function formatLots(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v >= 1e4 ? `${(v / 1e4).toFixed(2)}万手` : `${v.toFixed(0)}手`
}

export function formatPct(v: number | null | undefined, signed = true): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${signed && v > 0 ? '+' : ''}${v.toFixed(2)}%`
}

// A-share colours: red up, green down.
export function upDownClass(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return ''
  return v > 0 ? 'up' : 'down'
}

// Share counts as 亿 / 万 (股).
export function formatShares(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  if (Math.abs(v) >= 1e8) return `${(v / 1e8).toFixed(2)}亿`
  if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(0)}万`
  return v.toFixed(0)
}
