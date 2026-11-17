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
  name: string
  code: string
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
  options: () => request<Options>('/api/options'),
  startRun: (ticker: string, options?: Partial<RunOptions>) =>
    request<RunSummary>('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker, options }),
    }),
  runs: () => request<RunSummary[]>('/api/runs'),
  reports: () => request<ReportMeta[]>('/api/reports'),
  market: (date?: string) => request<MarketTable>(`/api/market${date ? `?date=${date}` : ''}`),
  marketCalendar: () => request<MarketCalendar>('/api/market/calendar'),
  marketStats: (range: StatsRange, end?: string) =>
    request<MarketStats>(`/api/market/stats?range=${range}${end ? `&end=${end}` : ''}`),
  marketSectors: (days: number, end?: string) =>
    request<MarketSectors>(`/api/market/sectors?days=${days}${end ? `&end=${end}` : ''}`),
  marketCrowding: (end?: string) => request<MarketCrowding>(`/api/market/crowding${end ? `?end=${end}` : ''}`),
  marketValuation: (end?: string) => request<MarketValuation>(`/api/market/valuation${end ? `?end=${end}` : ''}`),
  marketMargin: (range: StatsRange, end?: string) =>
    request<MarketMargin>(`/api/market/margin?range=${range}${end ? `&end=${end}` : ''}`),
  marketQvix: (range: StatsRange, end?: string) =>
    request<MarketQvix>(`/api/market/qvix?range=${range}${end ? `&end=${end}` : ''}`),
  marketFlow: (range: StatsRange, end?: string) =>
    request<MarketFlow>(`/api/market/flow?range=${range}${end ? `&end=${end}` : ''}`),
  industryFlow: (span: FlowSpan, date?: string) =>
    request<IndustryFlow>(`/api/market/flow/industry?span=${span}${date ? `&date=${date}` : ''}`),
  marketReleases: (date?: string) => request<MarketReleases>(`/api/market/releases${date ? `?date=${date}` : ''}`),
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
