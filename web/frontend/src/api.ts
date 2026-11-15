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

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* not JSON */
    }
    throw new Error(detail)
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
