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
}

export interface Settings {
  llm_provider: string | null
  deep_think_llm: string | null
  quick_think_llm: string | null
  output_language: string | null
  research_rounds: number | null
  risk_rounds: number | null
  analysts: string[]
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
  settings: () => request<Settings>('/api/settings'),
  startRun: (ticker: string) =>
    request<RunSummary>('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker }),
    }),
  runs: () => request<RunSummary[]>('/api/runs'),
  reports: () => request<ReportMeta[]>('/api/reports'),
  report: (id: string) => request<Report>(`/api/reports/${encodeURIComponent(id)}`),
  kline: (ticker: string, end?: string, days = 250) => {
    const q = new URLSearchParams({ days: String(days) })
    if (end) q.set('end', end)
    return request<{ symbol: string; bars: Bar[] }>(`/api/kline/${encodeURIComponent(ticker)}?${q}`)
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
