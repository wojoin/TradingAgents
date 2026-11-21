<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type SeriesType,
  type Time,
} from 'lightweight-charts'
import { api, formatPct, formatYuan, type Kline, type ReboundSignal, type StockRebound } from '../api'
import { bollWidth, cci, dmi, kdj, macd, obv, rsi, sma, wr, type Series } from '../indicators'
import { GapBands, findGaps, sixMonthsBefore, type Gap } from '../gapBands'
import { aggregate, isMinute, type KlineHover, type MinuteHover, type Period } from '../kperiod'
import IntradayChart from './IntradayChart.vue'

// Daily candles with moving averages, and three lower panes, each showing an indicator
// picked from a list (volume, amount, turnover, MACD, KDJ, RSI, OBV, BOLL width, WR, CCI, DMI)
// whose parameters can be changed in place.
//   full      the stock's whole history from the local store (since listing), opening on the last year
//   fit       size the chart to the screen: candles and all three panes within one screen
//   end       last day to draw; markDate puts a marker on that day
const props = defineProps<{
  ticker: string; end?: string | null; markDate?: string | null; days?: number; full?: boolean; fit?: boolean
  // external: the page shows the bar under the mouse in its own card (the 'hover' event), so the
  // chart's own heading leaves out the date, open, high, low, close and amount.
  external?: boolean
}>()
const emit = defineEmits<{ hover: [h: KlineHover | null] }>()

type Kind = 'VOL' | 'AMT' | 'TURN' | 'MACD' | 'KDJ' | 'RSI' | 'OBV' | 'BOLLW' | 'WR' | 'CCI' | 'DMI'
type ParamKind = Exclude<Kind, 'VOL' | 'AMT' | 'TURN'>
type Legend = [string, string, string][]   // [label, value, colour]
const KINDS: { value: Kind; label: string; tip: string }[] = [
  { value: 'VOL', label: '成交量', tip: '成交量与 5 / 10 / 20 日均量' },
  { value: 'AMT', label: '成交额', tip: '成交额与 5 / 10 / 20 日均额' },
  { value: 'TURN', label: '换手率', tip: '换手率（成交量 ÷ 流通股本）与 5 / 10 / 20 日均值：比成交量更便于跨股票比较活跃度' },
  { value: 'MACD', label: 'MACD', tip: '趋势与动能' },
  { value: 'KDJ', label: 'KDJ', tip: '随机指标：超买超卖' },
  { value: 'RSI', label: 'RSI', tip: '相对强弱：超买超卖' },
  { value: 'OBV', label: 'OBV', tip: '能量潮：涨日加量、跌日减量的累计；价格创新高而 OBV 不跟，是量价背离' },
  { value: 'BOLLW', label: 'BOLL宽度', tip: '布林带宽度（上下轨距离 ÷ 中轨）与 %B（收盘在带中的位置）：带宽收窄常在变盘之前。红线 = 上轨（%B 100），绿线 = 下轨（%B 0）：%B 越过红线即收盘在上轨之上，跌破绿线即在下轨之下' },
  { value: 'WR', label: 'WR', tip: '威廉指标：0–20 超买，80–100 超卖（通达信口径）' },
  { value: 'CCI', label: 'CCI', tip: '顺势指标：+100 以上强势，−100 以下弱势' },
  { value: 'DMI', label: 'DMI', tip: '趋向指标：ADX > 25 有趋势（+DI 在上为涨势），< 20 为震荡' },
]
const UP = '#e5484d'
const DOWN = '#1f9d55'
const C5 = '#111827'      // black
const C10 = '#f59e0b'     // orange
const C20 = '#dc2626'     // red
const PRICE_MAS: [number, string][] = [
  [5, C5], [10, C10], [20, C20], [60, '#16a34a'], [144, '#9333ea'], [233, '#92400e'],
]
const VOL_MAS: [number, string][] = [[5, C5], [10, C10], [20, C20]]
const LINE3 = [C5, C10, '#9333ea', '#16a34a']   // the lines of MACD / KDJ / RSI / DMI …
const RANGES: [string, number][] = [['3月', 63], ['1年', 250], ['3年', 750], ['全部', 0]]
const PANES = 3
const FIXED_HEIGHT = 900           // without ``fit``
const FOOT_ROOM = 52               // the line under the chart, the card's and the page's bottom padding
const DEFAULT_KINDS: Kind[] = ['VOL', 'MACD', 'KDJ']

// Indicator parameters, editable: each one's names and defaults (通达信's).
const PARAM_SPEC: Record<ParamKind, { names: string[]; defaults: number[] }> = {
  MACD: { names: ['快线', '慢线', '信号'], defaults: [12, 26, 9] },
  KDJ: { names: ['N', 'M1', 'M2'], defaults: [9, 3, 3] },
  RSI: { names: ['N1', 'N2', 'N3'], defaults: [6, 12, 24] },
  OBV: { names: ['M'], defaults: [30] },
  BOLLW: { names: ['N', 'P'], defaults: [20, 2] },
  WR: { names: ['N1', 'N2'], defaults: [10, 6] },
  CCI: { names: ['N'], defaults: [14] },
  DMI: { names: ['N', 'M'], defaults: [14, 6] },
}
const PARAM_KINDS = Object.keys(PARAM_SPEC) as ParamKind[]
const hasParams = (k: Kind): k is ParamKind => k in PARAM_SPEC
// Reference lines drawn across a pane: [value, label, colour (grey dashed when omitted)].
// BOLL宽度: %B is 100 on the upper band and 0 on the lower one.
const LEVELS: Partial<Record<Kind, [number, string, string?][]>> = {
  WR: [[20, '超买'], [80, '超卖']], CCI: [[100, '+100'], [-100, '−100']], DMI: [[25, '趋势'], [20, '']],
  BOLLW: [[100, '上轨', C20], [0, '下轨', '#16a34a']],
}
const STORE = { kinds: 'kline.panes', params: 'kline.params' }

function load<T>(key: string, fallback: T, ok: (v: unknown) => boolean): T {
  try {
    const v = JSON.parse(localStorage.getItem(key) || 'null')
    return ok(v) ? (v as T) : fallback
  } catch {
    return fallback
  }
}
function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* storage unavailable: settings last for this page only */
  }
}
const validKinds = (v: unknown) => Array.isArray(v) && v.length === PANES && v.every((k) => KINDS.some((o) => o.value === k))
const validSet = (k: ParamKind, p: unknown) =>
  Array.isArray(p) && p.length === PARAM_SPEC[k].defaults.length && p.every((n) => Number.isInteger(n) && n >= 1 && n <= 250)
// Saved parameters: each indicator's own when valid, else its defaults (settings saved before an
// indicator was added simply lack it).
function loadParams(): Record<ParamKind, number[]> {
  const saved = load<Record<string, unknown>>(STORE.params, {}, (v) => !!v && typeof v === 'object')
  return Object.fromEntries(PARAM_KINDS.map((k) => [k, validSet(k, saved[k]) ? (saved[k] as number[]) : [...PARAM_SPEC[k].defaults]])) as
    Record<ParamKind, number[]>
}

const el = ref<HTMLDivElement>()
const error = ref('')
const loading = ref(false)
const data = ref<Kline | null>(null)
const hoverIndex = ref<number | null>(null)
const range = ref(250)
const kinds = ref<Kind[]>(load(STORE.kinds, [...DEFAULT_KINDS], validKinds))
// The last six months' price gaps between adjacent candles, as grey bands across the price pane; can be hidden.
const showGaps = ref<boolean>(load('kline.gaps', true, (v) => typeof v === 'boolean'))
const gapCount = ref(0)
let gapBands: GapBands | null = null
let gapList: Gap[] = []
let candleSeries: ISeriesApi<'Candlestick'> | null = null
// 超跌反转 signals (A-shares): arrows under the candles, purple when the market condition held.
const rebound = ref<StockRebound | null>(null)
const showRebound = ref<boolean>(load('kline.rebound', true, (v) => typeof v === 'boolean'))
// ★ 单笔最优: the second rule's buys (★ under the 反) and sales (a large gold square with the return).
const showBest = ref<boolean>(load('kline.best', true, (v) => typeof v === 'boolean'))
type BestTrade = NonNullable<StockRebound['best']>['trades'][number]
const bestByBuy = computed(() => new Map((rebound.value?.best?.trades || []).map((t) => [t.date, t])))
const bestBySale = computed(() => new Map((rebound.value?.best?.trades || []).filter((t) => t.exit_date).map((t) => [t.exit_date as string, t])))
const shownBestBuy = computed<BestTrade | null>(() => (showBest.value && shown.value ? bestByBuy.value.get(shown.value.time) ?? null : null))
const shownBestSale = computed<BestTrade | null>(() => (showBest.value && shown.value ? bestBySale.value.get(shown.value.time) ?? null : null))
const BEST_HOW: Record<string, string> = { 盈: '止盈 +25%', 止: '止损 −30%', 期: '持满 250 个交易日', 卖: '出现「卖」信号，次日开盘' }
// 避: a sell / avoid signal with no position held: likely to lag from here, so wait before buying.
const showAvoid = ref<boolean>(load('kline.avoid', true, (v) => typeof v === 'boolean'))
let markers: ISeriesMarkersPluginApi<Time> | null = null
const reboundByDay = computed(() => new Map((rebound.value?.signals || []).map((x) => [x.date, x])))
const shownSignal = computed<ReboundSignal | null>(() => (shown.value ? reboundByDay.value.get(shown.value.time) ?? null : null))
// The trades a 卖 closes (sold at the next day's open): by the 卖's date.
const closedBySell = computed(() => {
  const m = new Map<string, ReboundSignal[]>()
  for (const x of rebound.value?.signals || []) {
    const d = x.trade?.exit === '卖' ? x.trade.sell_date : null
    if (d) m.set(d, [...(m.get(d) || []), x])
  }
  return m
})
const shownClosed = computed(() => (shown.value ? closedBySell.value.get(shown.value.time) ?? [] : []))
// 盈 / 止 / 期: the trade sold on the day by its target, stop or time limit.
const EXIT_STYLE: Record<string, { color: string; label: string; how: string }> = {
  盈: { color: '#d97706', label: '止盈卖出', how: '盘中最高价达到买入价 +30%，按止盈价卖出' },
  止: { color: '#16a34a', label: '止损卖出', how: '盘中最低价跌到买入价 −15%，按止损价卖出' },
  期: { color: '#2563eb', label: '到期卖出', how: '持满 20 个交易日，当天收盘卖出' },
}
const exitByDay = computed(() => new Map((rebound.value?.signals || [])
  .filter((x) => x.trade?.exit_date && x.trade.exit in EXIT_STYLE).map((x) => [x.trade!.exit_date as string, x])))
const shownExit = computed<ReboundSignal | null>(() => (shown.value ? exitByDay.value.get(shown.value.time) ?? null : null))
const sellByDay = computed(() => new Map((rebound.value?.sells || []).map((x) => [x.date, x])))
const shownSell = computed(() => {
  const x = shown.value ? sellByDay.value.get(shown.value.time) ?? null : null
  return x && (x.closes || showAvoid.value) ? x : null
})
const pctText = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)
// The gaps under the mouse (latest first) and where to show them.
const gapTip = ref<{ gaps: Gap[]; x: number; y: number; flip: boolean } | null>(null)
const params = reactive<Record<ParamKind, number[]>>(loadParams())
// What the settings panel edits, applied to ``params`` as soon as it is valid.
const draft = reactive<Record<ParamKind, (number | null)[]>>(
  Object.fromEntries(PARAM_KINDS.map((k) => [k, [...params[k]]])) as Record<ParamKind, (number | null)[]>,
)
const editing = ref<number | null>(null)          // which pane's settings panel is open
const paneTops = ref<number[]>([])
let chart: IChartApi | null = null

// The crosshair's date: YYYY-MM-DD whether the library hands it as a string, a business
// day or a timestamp.
function formatDay(t: Time): string {
  if (typeof t === 'string') return t
  if (typeof t === 'number') {
    const d = new Date(t * 1000)
    return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`
  }
  return `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}`
}
let paneSeries: ISeriesApi<SeriesType>[][] = []
let indexByTime = new Map<string, number>()
let resizer: ResizeObserver | null = null
const frame = ref<HTMLDivElement>()
const height = ref(FIXED_HEIGHT)
// Each lower pane's fixed height: a sixth of the chart, 80 to 150 px; the candles take the rest.
const paneHeight = computed(() => Math.max(80, Math.min(150, Math.round(height.value * 0.16))))

// 五日 (minute by minute), 日K, 周K, 月K: the week's and month's candles built from the days.
const PERIODS: { value: Period; label: string }[] = [
  { value: '1d', label: '分时' }, { value: 'day', label: '日K' }, { value: 'week', label: '周K' }, { value: 'month', label: '月K' },
  { value: '5d', label: '五日' },
]
// Each chart opens on 日K (the choice is not remembered).
const period = ref<Period>('day')
const isDay = computed(() => period.value === 'day')
const aShare = computed(() => /\d{6}/.test(props.ticker))
const bars = computed(() => aggregate(data.value?.bars || [], period.value))
// The range buttons are in trading days; a week is 5 of them and a month about 21.
const PER_BAR: Record<Period, number> = { '1d': 1, '5d': 1, day: 1, week: 5, month: 21 }
const idx = computed(() => hoverIndex.value ?? bars.value.length - 1)
const shown = computed(() => bars.value[idx.value] || null)
const lots = (v: number) => (data.value?.volume_unit === '股' ? v / 100 : v)
const fmtLots = (v: number | null | undefined) => {
  if (v === null || v === undefined) return '—'
  const x = lots(v)
  return x >= 1e4 ? `${(x / 1e4).toFixed(2)}万` : x.toFixed(0)
}
const fmt = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? '—' : v.toFixed(d)

const closes = computed(() => bars.value.map((x) => x.close))
const priceMa = computed(() => PRICE_MAS.map(([n]) => sma(closes.value, n)))
const volMa = computed(() => VOL_MAS.map(([n]) => sma(bars.value.map((x) => x.volume), n)))
const macdData = computed(() => macd(closes.value, ...(params.MACD as [number, number, number])))
const kdjData = computed(() =>
  kdj(bars.value.map((x) => x.high), bars.value.map((x) => x.low), closes.value, ...(params.KDJ as [number, number, number])),
)
const rsiData = computed(() => params.RSI.map((n) => rsi(closes.value, n)))
const highs = computed(() => bars.value.map((x) => x.high))
const lows = computed(() => bars.value.map((x) => x.low))
const amounts = computed(() => bars.value.map((x) => x.amount ?? null))
const turnovers = computed(() => bars.value.map((x) => x.turnover ?? null))
// Moving averages over a series with gaps (a bar without the figure): null where any is missing.
const maOf = (vals: (number | null)[], n: number): Series =>
  vals.some((v) => v === null)
    ? vals.map((_, i) => (i < n - 1 || vals.slice(i - n + 1, i + 1).some((v) => v === null) ? null
      : (vals.slice(i - n + 1, i + 1) as number[]).reduce((a, b) => a + b, 0) / n))
    : sma(vals as number[], n)
const amtMa = computed(() => VOL_MAS.map(([n]) => maOf(amounts.value, n)))
const turnMa = computed(() => VOL_MAS.map(([n]) => maOf(turnovers.value, n)))
const obvData = computed(() => obv(closes.value, bars.value.map((x) => lots(x.volume)), params.OBV[0]))
const bollData = computed(() => bollWidth(closes.value, params.BOLLW[0], params.BOLLW[1]))
const wrData = computed(() => params.WR.map((n) => wr(highs.value, lows.value, closes.value, n)))
const cciData = computed(() => cci(highs.value, lows.value, closes.value, params.CCI[0]))
const dmiData = computed(() => dmi(highs.value, lows.value, closes.value, params.DMI[0], params.DMI[1]))
const fmtBig = (v: number | null | undefined, unit = '') =>
  v === null || v === undefined || Number.isNaN(v) ? '—'
    : Math.abs(v) >= 1e8 ? `${(v / 1e8).toFixed(2)}亿${unit}` : Math.abs(v) >= 1e4 ? `${(v / 1e4).toFixed(2)}万${unit}` : `${v.toFixed(0)}${unit}`

watch([shown, hoverIndex, period], () => {
  if (!props.external) return
  if (isMinute(period.value)) onMinute(null)
  else if (!shown.value) emit('hover', null)
  else emit('hover', { bar: shown.value, change: change.value, period: period.value, latest: hoverIndex.value === null })
})
// 分时 / 五日: the minute under the mouse, with its day's daily candle (open, high, low); off the
// chart, the latest day's candle.
function onMinute(m: (MinuteHover & { change: number | null }) | null) {
  if (!props.external) return
  const days = data.value?.bars || []
  const day = (m && days.find((b) => b.time === m.date)) || days[days.length - 1]
  if (!day) return emit('hover', null)
  emit('hover', { bar: day, change: m ? m.change : day.pct_chg ?? null, period: period.value, latest: !m, minute: m })
}

const change = computed(() => {
  const b = shown.value
  if (!b) return null
  if (b.pct_chg !== undefined && b.pct_chg !== null) return b.pct_chg
  const prev = bars.value[idx.value - 1]
  return prev ? ((b.close - prev.close) / prev.close) * 100 : null
})

function legend(kind: Kind): Legend {
  const i = idx.value
  if (!shown.value) return []
  switch (kind) {
    case 'VOL':
      return [['VOL', fmtLots(shown.value.volume), '#4b5563'],
        ...VOL_MAS.map(([n, c], k) => [`MA${n}`, fmtLots(volMa.value[k][i]), c] as [string, string, string])]
    case 'MACD': {
      const m = macdData.value
      return [['DIF', fmt(m.dif[i], 3), LINE3[0]], ['DEA', fmt(m.dea[i], 3), LINE3[1]],
        ['MACD', fmt(m.bar[i], 3), m.bar[i] >= 0 ? UP : DOWN]]
    }
    case 'KDJ': {
      const k = kdjData.value
      return [['K', fmt(k.k[i]), LINE3[0]], ['D', fmt(k.d[i]), LINE3[1]], ['J', fmt(k.j[i]), LINE3[2]]]
    }
    case 'RSI':
      return params.RSI.map((n, k) => [`RSI${n}`, fmt(rsiData.value[k][i]), LINE3[k]] as [string, string, string])
    case 'AMT':
      return [['AMT', fmtBig(shown.value.amount), '#4b5563'],
        ...VOL_MAS.map(([n, c], k) => [`MA${n}`, fmtBig(amtMa.value[k][i]), c] as [string, string, string])]
    case 'TURN':
      return [['换手', shown.value.turnover === null || shown.value.turnover === undefined ? '—' : `${fmt(shown.value.turnover)}%`, '#4b5563'],
        ...VOL_MAS.map(([n, c], k) => [`MA${n}`, fmt(turnMa.value[k][i]), c] as [string, string, string])]
    case 'OBV':
      return [['OBV', fmtBig(obvData.value.obv[i]), LINE3[0]], [`MAOBV${params.OBV[0]}`, fmtBig(obvData.value.ma[i]), LINE3[1]]]
    case 'BOLLW':
      return [['宽度%', fmt(bollData.value.width[i]), LINE3[0]], ['%B', fmt(bollData.value.pctB[i], 1), LINE3[1]],
        ['上轨', '%B=100', C20], ['下轨', '%B=0', '#16a34a']]
    case 'WR':
      return params.WR.map((n, k) => [`WR${n}`, fmt(wrData.value[k][i]), LINE3[k]] as [string, string, string])
    case 'CCI':
      return [[`CCI${params.CCI[0]}`, fmt(cciData.value[i]), LINE3[0]]]
    case 'DMI': {
      const d = dmiData.value
      return [['+DI', fmt(d.pdi[i]), LINE3[0]], ['−DI', fmt(d.mdi[i]), LINE3[1]], ['ADX', fmt(d.adx[i]), LINE3[2]],
        ['ADXR', fmt(d.adxr[i]), LINE3[3]]]
    }
  }
}
const legends = computed(() => kinds.value.map((k) => legend(k)))
const title = (kind: Kind) => (hasParams(kind) ? `(${params[kind].join(',')})` : '')
// A pane whose figure this data source lacks (the vendor's bars for a non-A-share).
const missing = (kind: Kind) =>
  (kind === 'AMT' && !bars.value.some((b) => b.amount)) || (kind === 'TURN' && !bars.value.some((b) => b.turnover))

const points = (s: Series | number[]) =>
  bars.value.flatMap((b, i) => (s[i] === null || s[i] === undefined ? [] : [{ time: b.time as Time, value: s[i] as number }]))

function line(color: string, pane: number) {
  return chart!.addSeries(LineSeries, {
    color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
  }, pane)
}

// Draw pane ``p`` (1-based in the chart: pane 0 is the candles). New series go in before
// the old ones leave, so the pane is never empty and keeps its place.
function drawPane(p: number) {
  if (!chart || !bars.value.length) return
  const pane = p + 1
  const kind = kinds.value[p]
  const added: ISeriesApi<SeriesType>[] = []
  const lines = (list: (Series | number[])[]) =>
    list.forEach((s, k) => {
      const l = line(LINE3[k], pane)
      l.setData(points(s))
      added.push(l)
    })
  if (kind === 'VOL') {
    const h = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false }, pane)
    h.setData(bars.value.map((b) => ({ time: b.time as Time, value: b.volume, color: b.close >= b.open ? UP : DOWN })))
    added.push(h)
    VOL_MAS.forEach(([, color], k) => {
      const s = line(color, pane)
      s.setData(points(volMa.value[k]))
      added.push(s)
    })
  } else if (kind === 'MACD') {
    const m = macdData.value
    const h = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane)
    h.setData(bars.value.map((b, i) => ({ time: b.time as Time, value: m.bar[i], color: m.bar[i] >= 0 ? UP : DOWN })))
    added.push(h)
    lines([m.dif, m.dea])
  } else if (kind === 'KDJ') {
    const k = kdjData.value
    lines([k.k, k.d, k.j])
  } else if (kind === 'RSI') {
    lines(rsiData.value)
  } else if (kind === 'AMT' || kind === 'TURN') {
    const vals = kind === 'AMT' ? amounts.value : turnovers.value
    const fmtAxis = kind === 'AMT' ? (v: number) => fmtBig(v) : (v: number) => `${v.toFixed(2)}%`
    const h = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'custom', formatter: fmtAxis, minMove: 0.01 }, priceLineVisible: false, lastValueVisible: false,
    }, pane)
    h.setData(bars.value.flatMap((b, i) => (vals[i] === null ? [] : [{ time: b.time as Time, value: vals[i] as number,
      color: b.close >= b.open ? UP : DOWN }])))
    added.push(h)
    const mas = kind === 'AMT' ? amtMa.value : turnMa.value
    VOL_MAS.forEach(([, color], k) => {
      const s = line(color, pane)
      s.setData(points(mas[k]))
      added.push(s)
    })
  } else if (kind === 'OBV') {
    lines([obvData.value.obv, obvData.value.ma])
    added.forEach((x) => x.applyOptions({ priceFormat: { type: 'custom', formatter: (v: number) => fmtBig(v), minMove: 1 } }))
  } else if (kind === 'BOLLW') {
    lines([bollData.value.width, bollData.value.pctB])
  } else if (kind === 'WR') {
    lines(wrData.value)
  } else if (kind === 'CCI') {
    lines([cciData.value])
  } else {
    const d = dmiData.value
    lines([d.pdi, d.mdi, d.adx, d.adxr])
  }
  // Reference lines (超买 / 超卖, ±100, the ADX trend mark) on the pane's first series.
  for (const [value, label, color] of LEVELS[kind] || []) {
    added[0]?.createPriceLine({ price: value, color: color || '#9ca3af', lineWidth: 1, lineStyle: color ? 0 : 2,
                                axisLabelVisible: !!color, title: label })
  }
  ;(paneSeries[p] || []).forEach((s) => chart!.removeSeries(s))
  paneSeries[p] = added
  sizePanes()
}

// Each indicator list sits just under its pane's separator.
// Heights by stretch factor, set on every pane at once: the panes share the chart's height in
// proportion to their factors, so setting one pane's height while others are being added
// leaves the earlier ones squeezed. The candles take what the three fixed-height panes leave.
const AXIS = 28   // the time scale under the panes
function sizePanes() {
  if (!chart) return
  const panes = chart.panes()
  if (panes.length < PANES + 1) return
  const sub = paneHeight.value
  const main = Math.max(160, height.value - AXIS - PANES * (sub + 1))
  panes[0].setStretchFactor(main)
  for (let p = 1; p <= PANES; p++) panes[p].setStretchFactor(sub)
  place()
}

function place() {
  requestAnimationFrame(() => {
    if (!chart) return
    const tops: number[] = []
    let y = 0
    for (let p = 0; p <= PANES; p++) {
      if (p > 0) tops.push(y)
      y += chart.paneSize(p).height + 1
    }
    paneTops.value = tops
  })
}

function showRange(n: number) {
  range.value = n
  const total = bars.value.length
  if (!chart || !total) return
  n = n ? Math.ceil(n / PER_BAR[period.value]) : 0
  if (!n || n >= total) chart.timeScale().fitContent()
  else chart.timeScale().setVisibleLogicalRange({ from: total - n, to: total + 2 })
}

function onCrosshair(p: MouseEventParams) {
  hoverIndex.value = p.time !== undefined ? (indexByTime.get(String(p.time)) ?? null) : null
  // Over a gap band in the price pane: list the gaps whose price range holds the mouse.
  gapTip.value = null
  if (!showGaps.value || !p.point || (p.paneIndex ?? 0) !== 0 || !candleSeries || !gapList.length) return
  const price = candleSeries.coordinateToPrice(p.point.y)
  if (price === null) return
  const hits = gapList.filter((g) => price >= g.from && price <= g.to).slice(-3).reverse()
  if (hits.length) {
    const width = el.value?.clientWidth ?? 0
    gapTip.value = { gaps: hits, x: p.point.x, y: p.point.y, flip: p.point.x > width - 260 }
  }
}

async function draw() {
  if (!el.value) return
  chart?.remove()
  chart = null
  paneSeries = []
  candleSeries = null
  markers = null
  gapList = []
  gapTip.value = null
  error.value = ''
  hoverIndex.value = null
  loading.value = true
  try {
    const k = await api.kline(props.ticker, props.end || undefined, props.days ?? 250, props.full ? 'snapshot' : 'vendor')
    if (!k.bars.length) throw new Error('没有行情数据')
    data.value = k
    const kb = bars.value                       // the days, or the weeks / months built from them
    indexByTime = new Map(kb.map((b, i) => [b.time, i]))
    chart = createChart(el.value, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#ffffff' }, textColor: '#4b5563',
        panes: { separatorColor: '#d1d5db' },
        attributionLogo: false,   // credited in the footer link instead, as the library's licence allows
      },
      grid: { vertLines: { color: '#f1f3f6' }, horzLines: { color: '#f1f3f6' } },
      rightPriceScale: { borderColor: '#e3e7ec' },
      timeScale: { borderColor: '#e3e7ec' },
      // Dates as 2026-11-12 under the crosshair (the axis keeps its short labels).
      localization: { locale: 'zh-CN', timeFormatter: formatDay },
    })
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN, wickUpColor: UP, wickDownColor: DOWN,
    })
    candles.setData(kb.map((b) => ({ time: b.time as Time, open: b.open, high: b.high, low: b.low, close: b.close })))
    // Less headroom above the highest candle than the library's 20%.
    candles.priceScale().applyOptions({ scaleMargins: { top: 0.07, bottom: 0.04 } })
    candleSeries = candles
    gapBands = new GapBands()
    candles.attachPrimitive(gapBands)
    // Only the last six months' gaps, counted back from the last bar.
    const gaps = isDay.value ? findGaps(kb, sixMonthsBefore(kb[kb.length - 1].time)) : []   // daily gaps only
    gapCount.value = gaps.length
    gapList = gaps
    gapBands.setGaps(gaps)
    gapBands.setVisible(showGaps.value)
    PRICE_MAS.forEach(([, color], i) => line(color, 0).setData(points(priceMa.value[i])))
    markers = createSeriesMarkers(candles, [])
    setMarkers()
    loadRebound()
    for (let p = 0; p < PANES; p++) drawPane(p)
    chart.subscribeCrosshairMove(onCrosshair)
    if (props.full) showRange(range.value)
    else chart.timeScale().fitContent()
  } catch (e) {
    data.value = null
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

// The analysis-day arrow and, when shown, the 超跌反转 arrows, in time order as the library needs.
function setMarkers() {
  if (!markers || !data.value) return
  const list: SeriesMarker<Time>[] = []
  if (!isDay.value) {                         // the signals are daily: not on weekly or monthly candles
    markers.setMarkers([])
    return
  }
  const known = new Set(data.value.bars.map((b) => b.time))
  if (showRebound.value) {
    for (const x of rebound.value?.signals || []) {
      if (!known.has(x.date)) continue
      // Bought: purple; a purple 反 while already holding: light purple; grey: market condition not met.
      list.push({ time: x.date as Time, position: 'belowBar', shape: 'arrowUp', text: '反',
                  color: x.trade ? '#7c3aed' : x.market_ok ? '#c4b5fd' : '#a1a1aa' })
    }
  }
  if (showRebound.value) {
    // 盈 / 止 / 期: a trade sold by its target, stop or time limit, on the day it was sold.
    for (const x of rebound.value?.signals || []) {
      const t = x.trade
      if (!t?.exit_date || !(t.exit in EXIT_STYLE) || !known.has(t.exit_date)) continue
      list.push({ time: t.exit_date as Time, position: 'aboveBar', shape: 'arrowDown', text: t.exit,
                  color: EXIT_STYLE[t.exit].color })
    }
    // 卖: the day that sells a held trade (sold at the next open); 避: a sell / avoid signal with no
    // position held (light dot, hideable).
    for (const x of rebound.value?.sells || []) {
      if (!known.has(x.date)) continue
      if (x.closes) {
        list.push({ time: x.date as Time, position: 'aboveBar', shape: 'arrowDown', text: '卖', color: '#b91c1c' })
      } else if (showAvoid.value) {
        list.push({ time: x.date as Time, position: 'aboveBar', shape: 'circle', text: '避', color: '#fca5a5', size: 0.6 })
      }
    }
  }
  if (showBest.value) {
    for (const t of rebound.value?.best?.trades || []) {
      if (known.has(t.date)) {
        list.push({ time: t.date as Time, position: 'belowBar', shape: 'circle', text: '★', color: '#ca8a04', size: 1 })
      }
      if (t.exit_date && known.has(t.exit_date)) {
        const r = t.ret === null ? '' : ` ${t.ret > 0 ? '+' : ''}${t.ret.toFixed(1)}%`
        list.push({ time: t.exit_date as Time, position: 'aboveBar', shape: 'square', text: `★${t.exit}${r}`,
                    color: '#ca8a04', size: 2 })
      }
    }
  }
  if (props.markDate) {
    const at = [...data.value.bars].reverse().find((b) => b.time <= props.markDate!)
    if (at) list.push({ time: at.time as Time, position: 'aboveBar', color: '#2563eb', shape: 'arrowDown', text: '分析日' })
  }
  list.sort((a, b) => String(a.time).localeCompare(String(b.time)))
  markers.setMarkers(list)
}

async function loadRebound() {
  rebound.value = null
  const code = props.ticker.match(/\d{6}/)?.[0]
  if (!code) return                     // not an A-share code
  try {
    rebound.value = await api.stockRebound(code, props.end || undefined)
  } catch {
    rebound.value = null     // not an A-share in the store: no markers
  }
  setMarkers()
}

function setKind(p: number, kind: Kind) {
  kinds.value[p] = kind
  if (editing.value === p && !hasParams(kind)) editing.value = null
  save(STORE.kinds, kinds.value)
  drawPane(p)
}

// A parameter set is usable when every value is an integer from 1 to 250, MACD's fast < slow
// and BOLL's band width P at most 5 standard deviations.
function problem(kind: ParamKind): string {
  const v = draft[kind]
  if (v.some((n) => n === null || !Number.isInteger(n) || n < 1 || n > 250)) return '每个参数应为 1 到 250 的整数'
  if (kind === 'MACD' && (v[0] as number) >= (v[1] as number)) return '快线周期应小于慢线周期'
  if (kind === 'BOLLW' && (v[1] as number) > 5) return 'P（标准差倍数）应为 1 到 5'
  return ''
}

// Applied as soon as the draft is valid: recompute, and redraw the panes showing that indicator.
watch(draft, () => {
  for (const kind of PARAM_KINDS) {
    if (problem(kind) || draft[kind].every((n, i) => n === params[kind][i])) continue
    params[kind] = draft[kind].map(Number)
    save(STORE.params, params)
    kinds.value.forEach((k, p) => {
      if (k === kind) drawPane(p)
    })
  }
}, { deep: true })

watch(showRebound, (v) => {
  save('kline.rebound', v)
  setMarkers()
})
watch(showBest, (v) => {
  save('kline.best', v)
  setMarkers()
})
watch(showAvoid, (v) => {
  save('kline.avoid', v)
  setMarkers()
})

watch(showGaps, (v) => {
  save('kline.gaps', v)
  gapBands?.setVisible(v)
  if (!v) gapTip.value = null
})

function reset(kind: ParamKind) {
  draft[kind] = [...PARAM_SPEC[kind].defaults]
}

// With ``fit``, the chart runs from where it starts on the page to the bottom of the
// window, so the candles and the three panes share one screen; when too little of the
// window is left below it, it takes the window's height less the room for its headings,
// to fit once scrolled to. Recomputed when the window (or the screen it is on) changes.
function fitHeight() {
  if (!props.fit || !frame.value) return
  const top = frame.value.getBoundingClientRect().top + window.scrollY
  let h = window.innerHeight - top - FOOT_ROOM
  if (h < 460) h = window.innerHeight - 140
  height.value = Math.max(420, Math.round(h))
  requestAnimationFrame(() => {
    if (!chart) return
    sizePanes()
  })
}

onMounted(() => {
  fitHeight()
  draw()
  window.addEventListener('resize', fitHeight)
  if (el.value) {
    resizer = new ResizeObserver(place)
    resizer.observe(el.value)
  }
})
watch(() => [props.ticker, props.end, props.days, props.full], draw)
watch(period, (v, old) => {
  if (!isMinute(v)) {
    if (isMinute(old)) requestAnimationFrame(() => draw())   // the chart was hidden: draw it afresh
    else draw()
  }
})
watch(loading, (v) => {
  if (!v) fitHeight()           // headings above the chart may have changed height
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', fitHeight)
  resizer?.disconnect()
  chart?.remove()
})
</script>

<template>
  <div>
    <div class="row head">
      <strong v-if="!external">{{ data?.name || ticker }}</strong>
      <span class="periods">
        <button v-for="p in PERIODS.filter((x) => !isMinute(x.value) || aShare)" :key="p.value" :class="{ on: period === p.value }"
                @click="period = p.value">{{ p.label }}</button>
      </span>
      <template v-if="shown && !isMinute(period) && !external">
        <span class="muted num">{{ shown.time }}{{ period === 'week' ? ' 周' : period === 'month' ? ' 月' : '' }}</span>
        <span class="num">开 {{ shown.open.toFixed(2) }}</span>
        <span class="num">高 {{ shown.high.toFixed(2) }}</span>
        <span class="num">低 {{ shown.low.toFixed(2) }}</span>
        <span :class="['num', (change ?? 0) > 0 ? 'up' : (change ?? 0) < 0 ? 'down' : '']">
          收 {{ shown.close.toFixed(2) }} {{ formatPct(change) }}
        </span>
        <span v-if="shown.amount" class="num muted">额 {{ formatYuan(shown.amount) }}</span>
      </template>
      <span v-if="loading" class="muted"><i class="pi pi-spin pi-spinner" /> 加载中</span>
      <span class="spacer" />
      <label v-if="isDay && bars.length && rebound" class="gap-toggle"
             :title="`${rebound.rule}\n\n${rebound.stats}\n\n紫色箭头：市场条件满足；灰色：不满足或${rebound.market_since ? ` ${rebound.market_since} 前` : ''}无市场数据。\n买入：没有持仓时的紫色「反」，次日开盘一次性买入。卖出（一次性卖光，先到先卖）：橙「盈」= 涨到买入价 +30%；绿「止」= 跌到 −15%；蓝「期」= 持满 20 个交易日；红「卖」= 出现卖出信号，次日开盘。一次只持一笔，买卖严格交替。浅红圆点「避」= 没有持仓时出现的卖出信号，之后大概率跑输，先别买。\n浅紫「反」：持仓期间出现，不重复买入；灰色「反」：市场条件不满足或 2024-09 前无市场数据，不买。\n\n${rebound.sell_rule || ''}\n${rebound.sell_stats || ''}\n上方红色「卖」：买入后第一次出现的卖出信号，次日开盘全部卖出（每一笔只有这一个卖点）。`">
        <input v-model="showRebound" type="checkbox" /> 买卖信号 买 {{ rebound.signals.filter((x) => x.trade).length }} · 卖出 {{ rebound.signals.filter((x) => x.trade && x.trade.exit !== '持有中' && x.trade.exit !== '待买入').length }}
      </label>
      <label v-if="isDay && bars.length && rebound && showRebound" class="gap-toggle"
             title="「避」：没有持仓时出现的卖出 / 规避信号（20 日涨幅 > 30%，或强上升趋势中 MACD 金叉且 ADX 走高）。之后大概率跑输，先别买；与已有持仓无关。">
        <input v-model="showAvoid" type="checkbox" /> 避 {{ rebound.sells?.filter((x) => !x.closes).length ?? 0 }}
      </label>
      <label v-if="isDay && bars.length && rebound?.best" class="gap-toggle best-toggle"
             :title="`${rebound.best.rule}\n\n${rebound.best.stats}\n\n金色「★」：这套规则的买入点（同一个紫色「反」）；金色大方块「★盈/止/期/卖 +x%」：它的卖出点与这一笔的收益。`">
        <input v-model="showBest" type="checkbox" /> ★ 单笔最优 {{ rebound.best.trades.length }}
      </label>
      <label v-if="isDay && bars.length" class="gap-toggle" :title="`最近半年相邻两日的跳空缺口：共 ${gapCount} 个`">
        <input v-model="showGaps" type="checkbox" /> 近半年缺口 {{ gapCount }}
      </label>
      <span v-if="full && bars.length && !isMinute(period)" class="ranges">
        <button v-for="[label, n] in RANGES" :key="label" :class="{ on: range === n }" @click="showRange(n)">{{ label }}</button>
      </span>
    </div>
    <div v-if="shownSignal && showRebound" class="signal small">
      <b>超跌反转信号 {{ shownSignal.date }}</b>：{{ shownSignal.trigger }} · 超卖 {{ shownSignal.oversold }} · ADX {{ shownSignal.adx }}
      （−DI {{ shownSignal.mdi }} &gt; +DI {{ shownSignal.pdi }}） · 成交额为前 5 日均值的 {{ shownSignal.amt_ratio }} 倍 ·
      <span :class="shownSignal.market_ok ? 'ok' : 'muted'">市场条件{{ shownSignal.market_ok === null ? '无数据' : shownSignal.market_ok ? '满足' : '不满足' }}</span>
      <span class="muted">（历史统计：止盈 30% / 止损 15% / 期限 20 日：每笔平均 +2.0%、胜率 52%、每年超额为正，平均持有 17 日；见指标说明）</span>
      <div v-if="shownSignal.skip" class="muted">这次不买入：{{ shownSignal.skip }}。</div>
      <div v-if="shownSignal.trade">
        这笔（按回测规则）：<template v-if="shownSignal.trade.exit === '待买入'">次日开盘买入</template>
        <template v-else>{{ shownSignal.trade.entry_date }} 开盘买入 →
          <template v-if="shownSignal.trade.exit === '持有中'">持有中（{{ shownSignal.trade.days }} 日；止盈价 {{ shownSignal.trade.target_price }}、止损价 {{ shownSignal.trade.stop_price }}、最晚第 20 个交易日卖出），目前</template>
          <template v-else-if="shownSignal.trade.exit === '卖'">{{ shownSignal.trade.exit_date }} 开盘卖出（{{ shownSignal.trade.sell_date }} 出现「卖」，持有 {{ shownSignal.trade.days }} 日），</template>
          <template v-else>{{ shownSignal.trade.exit_date }} {{ EXIT_STYLE[shownSignal.trade.exit].label }}（{{ shownSignal.trade.exit_price }}，持有 {{ shownSignal.trade.days }} 日），</template>
          收益 <b :class="(shownSignal.trade.ret ?? 0) >= 0 ? 'up' : 'down'">{{ pctText(shownSignal.trade.ret) }}</b>（复权、未扣成本）
          <span v-if="shownSignal.trade.peak_ret !== null" class="muted">
            · 持有期间最高收盘 {{ pctText(shownSignal.trade.peak_ret) }}（{{ shownSignal.trade.peak_date }}；事后才知道，无法事先确定）
          </span>
        </template>
      </div>
    </div>
    <div v-if="shownExit && showRebound" class="signal exit small" :style="{ borderLeftColor: EXIT_STYLE[shownExit.trade!.exit].color }">
      <b>{{ EXIT_STYLE[shownExit.trade!.exit].label }}「{{ shownExit.trade!.exit }}」{{ shownExit.trade!.exit_date }}</b>：
      {{ shownExit.date }} 的「反」，{{ shownExit.trade!.entry_date }} 开盘买入（{{ shownExit.trade!.entry_price }}），{{ EXIT_STYLE[shownExit.trade!.exit].how }}
      （{{ shownExit.trade!.exit_price }}），持有 {{ shownExit.trade!.days }} 日，收益
      <b :class="(shownExit.trade!.ret ?? 0) >= 0 ? 'up' : 'down'">{{ pctText(shownExit.trade!.ret) }}</b>（复权、未扣成本）
      <span class="muted">· 持有期间最高收盘 {{ pctText(shownExit.trade!.peak_ret) }}（事后才知道）</span>
    </div>
    <div v-if="shownBestSale" class="signal best small">
      <b>★ 单笔最优 · 卖出 {{ shownBestSale.exit_date }}</b>：{{ shownBestSale.date }} 的「反」，{{ shownBestSale.entry_date }} 开盘买入（{{ shownBestSale.entry_price }}），
      {{ BEST_HOW[shownBestSale.exit] || shownBestSale.exit }}（{{ shownBestSale.exit_price }}），持有 {{ shownBestSale.days }} 日，收益
      <b :class="(shownBestSale.ret ?? 0) >= 0 ? 'up' : 'down'">{{ pctText(shownBestSale.ret) }}</b>（复权、未扣成本）
      <span class="muted">· 持有期间最高收盘 {{ pctText(shownBestSale.peak_ret) }}（事后才知道）</span>
    </div>
    <div v-if="shownBestBuy" class="signal best small">
      <b>★ 单笔最优 · 买入</b>：{{ shownBestBuy.entry_date }} 开盘买入（{{ shownBestBuy.entry_price }}），止盈价 {{ shownBestBuy.target_price }}（+25%）、止损价 {{ shownBestBuy.stop_price }}（−30%）、最长 250 个交易日 →
      <template v-if="shownBestBuy.exit === '持有中'">持有中（{{ shownBestBuy.days }} 日），目前</template>
      <template v-else>{{ shownBestBuy.exit_date }} {{ BEST_HOW[shownBestBuy.exit] || shownBestBuy.exit }}，</template>
      收益 <b :class="(shownBestBuy.ret ?? 0) >= 0 ? 'up' : 'down'">{{ pctText(shownBestBuy.ret) }}</b>
      <span class="muted">（历史统计：胜率 62.6%、每笔平均 +4.6%、平均持有 69 日）</span>
    </div>
    <div v-if="shownSell && showRebound" class="signal sell small">
      <b>{{ shownSell.closes ? '卖出信号' : '规避信号「避」' }} {{ shownSell.date }}</b>：{{ shownSell.reason }} · ADX {{ shownSell.adx }} ·
      <span :class="shownSell.market_weak ? 'bad' : 'muted'">市场条件{{ shownSell.market_weak === null ? '无数据' : shownSell.market_weak ? '走弱（信号更强）' : '走强' }}</span>
      <span class="muted">（历史统计：之后 20 日平均跑输大盘约 1.4%，市场走弱时约 1.7%；是跑输的概率高，不等于一定下跌）</span>
      <div v-if="!shownSell.closes" class="muted">没有持仓时出现：之后大概率跑输，先别买（与已有持仓无关）。</div>
      <div v-if="shownClosed.length">
        次日开盘全部卖出：<template v-for="(c, n) in shownClosed" :key="c.date"><template v-if="n">；</template>{{ c.date }} 的「反」（{{ c.trade!.entry_date }} 买入，持有 {{ c.trade!.days }} 日）
          收益 <b :class="(c.trade!.ret ?? 0) >= 0 ? 'up' : 'down'">{{ pctText(c.trade!.ret) }}</b>
          <span class="muted">（持有期间最高 {{ pctText(c.trade!.peak_ret) }}，{{ c.trade!.peak_date }}，事后才知道）</span></template>（复权、未扣成本）
      </div>
    </div>
    <!-- 分时 (today, with the call auction and the trade list) and 五日 share the minute chart. -->
    <IntradayChart v-if="isMinute(period) && aShare" :key="period" :code="ticker.match(/\d{6}/)?.[0] || ticker"
                   :days="period === '1d' ? 1 : 5" :height="height" @minute="onMinute" />
    <div v-show="!isMinute(period)">
    <div v-if="shown" class="row mas num">
      <span v-for="([n, color], i) in PRICE_MAS" :key="n" :style="{ color }">MA{{ n }}: {{ fmt(priceMa[i][idx]) }}</span>
    </div>
    <div v-if="error" class="muted error">K线加载失败：{{ error }}</div>
    <div ref="frame" class="frame">
      <div ref="el" class="chart" :style="{ height: `${height}px` }" />
      <div v-if="gapTip" class="gap-tip" :style="{ top: `${gapTip.y + 14}px`, left: gapTip.flip ? 'auto' : `${gapTip.x + 14}px`,
                                                   right: gapTip.flip ? `${(el?.clientWidth ?? 0) - gapTip.x + 14}px` : 'auto' }">
        <div v-for="g in gapTip.gaps" :key="g.time" class="gap-item">
          <div class="gap-head" :class="g.up ? 'up' : 'down'">{{ g.up ? '向上跳空' : '向下跳空' }} · {{ g.time }}</div>
          <template v-if="g.up">
            <div>当天最低价 <b>{{ g.low.toFixed(2) }}</b></div>
            <div>前一天（{{ g.prevTime }}）最高价 <b>{{ g.prevHigh.toFixed(2) }}</b></div>
          </template>
          <template v-else>
            <div>当天最高价 <b>{{ g.high.toFixed(2) }}</b></div>
            <div>前一天（{{ g.prevTime }}）最低价 <b>{{ g.prevLow.toFixed(2) }}</b></div>
          </template>
          <div class="muted">缺口 {{ (g.to - g.from).toFixed(2) }}（{{ ((g.to - g.from) / (g.up ? g.prevHigh : g.prevLow) * 100).toFixed(2) }}%）</div>
        </div>
      </div>
      <template v-if="bars.length">
        <div v-for="(top, p) in paneTops" :key="p" class="lower" :class="{ open: editing === p }" :style="{ top: `${top}px` }">
          <select :value="kinds[p]" class="pick" :aria-label="`副图${p + 1}指标`"
                  @change="setKind(p, ($event.target as HTMLSelectElement).value as Kind)">
            <option v-for="o in KINDS" :key="o.value" :value="o.value" :title="o.tip">{{ o.label }}</option>
          </select>
          <button v-if="hasParams(kinds[p])" class="gear" :class="{ on: editing === p }" :title="`${kinds[p]} 参数`"
                  @click="editing = editing === p ? null : p">
            <i class="pi pi-cog" />
          </button>
          <span class="muted small">{{ title(kinds[p]) }}</span>
          <span v-if="missing(kinds[p])" class="muted small">此行情来源没有{{ kinds[p] === 'AMT' ? '成交额' : '换手率' }}数据</span>
          <span v-for="[label, value, color] in legends[p]" v-else :key="label" class="num small" :style="{ color }">
            {{ label }}: {{ value }}
          </span>
          <i class="pi pi-question-circle hint" :title="KINDS.find((o) => o.value === kinds[p])?.tip" />
          <div v-if="editing === p && hasParams(kinds[p])" class="params">
            <template v-for="kind in [kinds[p] as ParamKind]" :key="kind">
              <div class="params-title">{{ KINDS.find((o) => o.value === kind)?.label }} 参数 <span class="muted">（修改后立即生效）</span></div>
              <div class="params-row">
                <label v-for="(name, i) in PARAM_SPEC[kind].names" :key="name">
                  {{ name }}
                  <input v-model.number="draft[kind][i]" type="number" min="1" max="250" step="1" />
                </label>
              </div>
              <div v-if="problem(kind)" class="bad small">{{ problem(kind) }}</div>
              <div class="params-row">
                <button class="link" @click="reset(kind)">恢复默认（{{ PARAM_SPEC[kind].defaults.join(',') }}）</button>
                <button class="link" @click="editing = null">关闭</button>
              </div>
            </template>
          </div>
        </div>
      </template>
    </div>
    <div v-if="data && bars.length" class="muted foot">
      {{ PERIODS.find((x) => x.value === period)?.label }} · {{ data.adjust }} · {{ bars[0].time }} 至 {{ bars[bars.length - 1].time }} · 共 {{ bars.length }} 根
      <template v-if="!isDay">（由日线合成：开盘取首日、收盘取末日、最高最低取极值、成交量额相加、涨跌幅按日连乘；买卖信号只在日K上标出）</template>
      <template v-if="data.source === 'snapshot'">
        · 本地快照：base 至 {{ data.base_through || '—' }}<template v-if="data.after_base">，之后 {{ data.after_base }} 个交易日来自每日快照</template>
      </template>
      <template v-else> · 来源：AKShare / Yahoo 行情</template>
      <span v-if="data.note"> · {{ data.note }}</span>
      · 拖动平移，滚轮缩放 ·
      图表：<a href="https://www.tradingview.com/" target="_blank" rel="noopener">TradingView Lightweight Charts</a>
    </div>
    </div>
  </div>
</template>

<style scoped>
.head { margin-bottom: 4px; gap: 10px; }
.mas { gap: 14px; font-size: 12px; margin-bottom: 6px; }
.spacer { flex: 1; }
.signal { margin: 0 0 6px; padding: 4px 8px; border-left: 3px solid #7c3aed; background: #f5f3ff; border-radius: 4px; line-height: 1.6; }
.signal .ok { color: #7c3aed; font-weight: 600; }
.signal.exit { border-left-color: #71717a; background: #f4f4f5; }
.signal.sell { border-left-color: #b91c1c; background: #fef2f2; }
.signal.best { border-left-color: #ca8a04; background: #fefce8; }
.best-toggle { color: #a16207; font-weight: 600; }
.signal .bad { color: #b91c1c; font-weight: 600; }
.gap-tip {
  position: absolute; z-index: 6; pointer-events: none; background: rgba(255, 255, 255, 0.96);
  border: 1px solid var(--border); border-radius: 6px; box-shadow: 0 4px 14px rgba(17, 24, 39, 0.12);
  padding: 8px 10px; font-size: 12px; line-height: 1.6; min-width: 200px;
}
.gap-item + .gap-item { border-top: 1px solid var(--border); margin-top: 6px; padding-top: 6px; }
.gap-head { font-weight: 600; }
.gap-head.up { color: var(--up); }
.gap-head.down { color: var(--down); }
.gap-toggle { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--muted); cursor: pointer; }
.periods { display: inline-flex; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
.periods button { border: 0; background: #fff; padding: 3px 10px; cursor: pointer; font: inherit; font-size: 12px; color: var(--muted); }
.periods button + button { border-left: 1px solid var(--border); }
.periods button.on { background: #2563eb; color: #fff; }
.ranges { display: inline-flex; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
.ranges button { border: 0; background: #fff; padding: 3px 10px; cursor: pointer; font: inherit; font-size: 12px; color: var(--muted); }
.ranges button + button { border-left: 1px solid var(--border); }
.ranges button.on { background: #2563eb; color: #fff; }
.frame { position: relative; }
.chart { width: 100%; }
.lower {
  position: absolute; left: 6px; z-index: 3; margin-top: 4px;
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  background: rgba(255, 255, 255, 0.85); padding: 2px 6px; border-radius: 4px; pointer-events: none;
}
/* The pane whose settings are open sits above the panes under it, so its panel is not covered. */
.lower.open { z-index: 8; }
.pick, .gear, .params, .hint { pointer-events: auto; }
.hint { font-size: 11px; color: var(--muted); cursor: help; }
.pick {
  font: inherit; font-size: 12px; padding: 1px 4px; border: 1px solid var(--border);
  border-radius: 4px; background: #fff; color: var(--text); cursor: pointer;
}
.gear { border: 1px solid var(--border); background: #fff; border-radius: 4px; padding: 1px 5px; cursor: pointer; color: var(--muted); font-size: 12px; }
.gear.on { color: #2563eb; border-color: #2563eb; }
.params {
  position: absolute; top: 100%; left: 0; margin-top: 4px; z-index: 5;
  background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px;
  box-shadow: 0 6px 20px rgba(17, 24, 39, 0.12); min-width: 260px;
}
.params-title { font-weight: 600; font-size: 13px; margin-bottom: 8px; }
.params-row { display: flex; gap: 12px; align-items: center; margin-top: 6px; flex-wrap: wrap; }
.params-row label { display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: var(--muted); }
.params-row input { width: 64px; font: inherit; font-size: 13px; padding: 3px 6px; border: 1px solid var(--border); border-radius: 4px; }
.link { border: 0; background: none; color: #2563eb; cursor: pointer; padding: 0; font: inherit; font-size: 12px; }
.bad { color: var(--up); margin-top: 6px; }
.small { font-size: 12px; }
.foot { margin-top: 6px; font-size: 12px; }
.foot a { color: var(--muted); }
.error { padding: 8px 0; }
</style>
