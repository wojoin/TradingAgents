// Weekly and monthly candles from daily ones: open of the first day, close of the last, the highest
// high and lowest low, volume, amount and turnover summed, the change compounded from each day's
// (so an ex-dividend gap inside the week is no fall). A candle is dated by its first trading day.
import type { Bar } from './api'

export type Period = '1d' | '5d' | 'day' | 'week' | 'month'
// 分时 and 五日 are minute charts, not candles.
export const isMinute = (p: Period) => p === '1d' || p === '5d'

// The bar under the mouse, for a page that shows it in its own card (latest: the mouse is off the
// chart, so it is the last bar).
export interface MinuteHover { date: string; time: string; price: number; avg: number | null; volume: number; amount: number }
// minute: on 分时 / 五日, the minute under the mouse (bar is then that day's daily candle).
export interface KlineHover { bar: Bar; change: number | null; period: Period; latest: boolean; minute?: MinuteHover | null }

// The Monday of a date's week (YYYY-MM-DD), so a week across a month end stays one candle.
function weekKey(t: string): string {
  const d = new Date(`${t}T00:00:00Z`)
  const back = (d.getUTCDay() + 6) % 7
  d.setUTCDate(d.getUTCDate() - back)
  return d.toISOString().slice(0, 10)
}

// The candle a day belongs to under ``period`` (its week's Monday, its month, or the day itself).
export function periodKey(day: string, period: Period): string {
  return period === 'month' ? day.slice(0, 7) : period === 'week' ? weekKey(day) : day
}

export function aggregate(bars: Bar[], period: Period): Bar[] {
  if (period !== 'week' && period !== 'month') return bars
  const key = period === 'month' ? (t: string) => t.slice(0, 7) : weekKey
  const out: Bar[] = []
  let cur: Bar | null = null
  let k = ''
  let growth = 1
  let pctKnown = true
  let prevClose: number | null = null
  const close = () => {
    if (!cur) return
    cur.pct_chg = pctKnown ? (growth - 1) * 100 : prevClose ? (cur.close / prevClose - 1) * 100 : null
    out.push(cur)
  }
  for (const b of bars) {
    const kb = key(b.time)
    if (!cur || kb !== k) {
      if (cur) prevClose = cur.close
      close()
      cur = { time: b.time, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume,
              amount: b.amount ?? null, turnover: b.turnover ?? null, pct_chg: null }
      k = kb
      growth = 1
      pctKnown = true
    } else {
      cur.high = Math.max(cur.high, b.high)
      cur.low = Math.min(cur.low, b.low)
      cur.close = b.close
      cur.volume += b.volume
      cur.amount = cur.amount !== null && cur.amount !== undefined && b.amount !== null && b.amount !== undefined
        ? cur.amount + b.amount : null
      cur.turnover = cur.turnover !== null && cur.turnover !== undefined && b.turnover !== null && b.turnover !== undefined
        ? cur.turnover + b.turnover : null
    }
    if (b.pct_chg === null || b.pct_chg === undefined) pctKnown = false
    else growth *= 1 + b.pct_chg / 100
  }
  close()
  return out
}
