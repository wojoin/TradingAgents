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
