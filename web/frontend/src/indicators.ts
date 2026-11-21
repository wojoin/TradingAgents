// Technical indicators for the K-line, on the conventions A-share terminals use.
// Every series is aligned with its input: index i is the value on bar i, null until
// the indicator has enough bars.

export type Series = (number | null)[]

// Simple moving average over n values.
export function sma(values: number[], n: number): Series {
  const out: Series = new Array(values.length).fill(null)
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= n) sum -= values[i - n]
    if (i >= n - 1) out[i] = sum / n
  }
  return out
}

// Exponential moving average with alpha 2/(n+1), seeded with the first value.
export function ema(values: number[], n: number): number[] {
  const k = 2 / (n + 1)
  const out: number[] = []
  values.forEach((v, i) => out.push(i === 0 ? v : v * k + out[i - 1] * (1 - k)))
  return out
}

// The "SMA(X, N, M)" of Chinese terminals: Y = (M*X + (N-M)*Y') / N, seeded with the first value.
function smaCn(values: number[], n: number, m: number, seed?: number): number[] {
  const out: number[] = []
  values.forEach((v, i) => out.push(i === 0 ? (seed ?? v) : (m * v + (n - m) * out[i - 1]) / n))
  return out
}

// MACD(fast, slow, signal): DIF = EMA(fast) - EMA(slow), DEA = EMA(DIF, signal),
// bar = 2 * (DIF - DEA), as A-share terminals draw it.
export function macd(closes: number[], fast = 12, slow = 26, signal = 9) {
  const f = ema(closes, fast)
  const s = ema(closes, slow)
  const dif = closes.map((_, i) => f[i] - s[i])
  const dea = ema(dif, signal)
  const bar = dif.map((d, i) => 2 * (d - dea[i]))
  return { dif, dea, bar }
}

// KDJ(n, m1, m2): RSV over n bars; K = SMA(RSV, m1, 1), D = SMA(K, m2, 1), J = 3K - 2D; K and D start at 50.
export function kdj(highs: number[], lows: number[], closes: number[], n = 9, m1 = 3, m2 = 3) {
  const rsv = closes.map((c, i) => {
    const from = Math.max(0, i - n + 1)
    const hi = Math.max(...highs.slice(from, i + 1))
    const lo = Math.min(...lows.slice(from, i + 1))
    return hi === lo ? 50 : ((c - lo) / (hi - lo)) * 100
  })
  const k = smaCn(rsv, m1, 1, 50)
  const d = smaCn(k, m2, 1, 50)
  const j = k.map((v, i) => 3 * v - 2 * d[i])
  return { k, d, j }
}

// RSI(n), Wilder-smoothed: SMA(max(change, 0), n, 1) / SMA(|change|, n, 1) * 100.
export function rsi(closes: number[], n: number): Series {
  const change = closes.map((c, i) => (i === 0 ? 0 : c - closes[i - 1]))
  const up = smaCn(change.map((x) => Math.max(x, 0)), n, 1)
  const all = smaCn(change.map((x) => Math.abs(x)), n, 1)
  return closes.map((_, i) => (i < n ? null : all[i] === 0 ? 50 : (up[i] / all[i]) * 100))
}

// Highest high / lowest low of the n bars to i (fewer at the start).
function hhv(values: number[], n: number): number[] {
  return values.map((_, i) => Math.max(...values.slice(Math.max(0, i - n + 1), i + 1)))
}
function llv(values: number[], n: number): number[] {
  return values.map((_, i) => Math.min(...values.slice(Math.max(0, i - n + 1), i + 1)))
}
// Sum of the n values to i, null until there are n.
function sum(values: number[], n: number): Series {
  return sma(values, n).map((v) => (v === null ? null : v * n))
}

// OBV (on-balance volume): the volume added on an up day, taken off on a down day, nothing on an
// unchanged one, from the first bar; MAOBV = MA(OBV, m).
export function obv(closes: number[], volumes: number[], m = 30) {
  const line: number[] = []
  closes.forEach((c, i) => {
    const prev = i === 0 ? 0 : line[i - 1]
    const d = i === 0 ? 0 : c > closes[i - 1] ? volumes[i] : c < closes[i - 1] ? -volumes[i] : 0
    line.push(prev + d)
  })
  return { obv: line, ma: sma(line, m) }
}

// Bollinger band width and %B (n bars, p standard deviations, population SD as terminals use):
// width = (UB − LB) ÷ MB × 100, a narrowing band often comes before a big move; %B = (C − LB) ÷
// (UB − LB) × 100: above 100 the close is over the upper band, below 0 under the lower.
export function bollWidth(closes: number[], n = 20, p = 2) {
  const mid = sma(closes, n)
  const width: Series = []
  const pctB: Series = []
  closes.forEach((c, i) => {
    const m = mid[i]
    if (m === null) {
      width.push(null)
      pctB.push(null)
      return
    }
    const win = closes.slice(i - n + 1, i + 1)
    const sd = Math.sqrt(win.reduce((s, x) => s + (x - m) ** 2, 0) / n)
    const ub = m + p * sd
    const lb = m - p * sd
    width.push(m ? ((ub - lb) / m) * 100 : null)
    pctB.push(ub === lb ? 50 : ((c - lb) / (ub - lb)) * 100)
  })
  return { width, pctB }
}

// Williams %R as 通达信 draws it: (HHV(H, n) − C) ÷ (HHV − LLV) × 100, so 0 is the top of the
// range (超买 below 20) and 100 the bottom (超卖 above 80).
export function wr(highs: number[], lows: number[], closes: number[], n: number): Series {
  const hi = hhv(highs, n)
  const lo = llv(lows, n)
  return closes.map((c, i) => (i < n - 1 ? null : hi[i] === lo[i] ? 50 : ((hi[i] - c) / (hi[i] - lo[i])) * 100))
}

// CCI(n): (TP − MA(TP, n)) ÷ (0.015 × mean absolute deviation of TP), TP = (H + L + C) ÷ 3.
// Above +100 a strong move, below −100 a weak one.
export function cci(highs: number[], lows: number[], closes: number[], n = 14): Series {
  const tp = closes.map((c, i) => (highs[i] + lows[i] + c) / 3)
  const ma = sma(tp, n)
  return tp.map((t, i) => {
    const m = ma[i]
    if (m === null) return null
    const dev = tp.slice(i - n + 1, i + 1).reduce((s, x) => s + Math.abs(x - m), 0) / n
    return dev === 0 ? 0 : (t - m) / (0.015 * dev)
  })
}

// DMI(n, m) as 通达信: +DI and −DI from the n-bar sums of directional movement over the true
// range; ADX = MA(|−DI − +DI| ÷ (−DI + +DI) × 100, m); ADXR = (ADX + ADX m bars ago) ÷ 2.
// ADX above 25 is a trend (its direction from +DI against −DI); below 20, a range.
export function dmi(highs: number[], lows: number[], closes: number[], n = 14, m = 6) {
  const tr = closes.map((_, i) => (i === 0 ? highs[0] - lows[0] : Math.max(highs[i] - lows[i],
    Math.abs(highs[i] - closes[i - 1]), Math.abs(closes[i - 1] - lows[i]))))
  const hd = highs.map((h, i) => (i === 0 ? 0 : h - highs[i - 1]))
  const ld = lows.map((l, i) => (i === 0 ? 0 : lows[i - 1] - l))
  const mtr = sum(tr, n)
  const dmp = sum(hd.map((h, i) => (h > 0 && h > ld[i] ? h : 0)), n)
  const dmm = sum(ld.map((l, i) => (l > 0 && l > hd[i] ? l : 0)), n)
  const pdi: Series = mtr.map((t, i) => (t === null || t === 0 || dmp[i] === null ? null : ((dmp[i] as number) * 100) / t))
  const mdi: Series = mtr.map((t, i) => (t === null || t === 0 || dmm[i] === null ? null : ((dmm[i] as number) * 100) / t))
  const dx = pdi.map((p, i) => {
    const q = mdi[i]
    return p === null || q === null ? null : p + q === 0 ? 0 : (Math.abs(q - p) / (q + p)) * 100
  })
  const start = dx.findIndex((v) => v !== null)
  const adx: Series = new Array(closes.length).fill(null)
  if (start >= 0) {
    const tail = sma(dx.slice(start) as number[], m)
    tail.forEach((v, k) => { adx[start + k] = v })
  }
  const adxr: Series = adx.map((a, i) => (a === null || i < m || adx[i - m] === null ? null : (a + (adx[i - m] as number)) / 2))
  return { pdi, mdi, adx, adxr }
}
