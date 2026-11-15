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
  type MouseEventParams,
  type SeriesType,
  type Time,
} from 'lightweight-charts'
import { api, formatPct, formatYuan, type Kline } from '../api'
import { kdj, macd, rsi, sma, type Series } from '../indicators'
import { GapBands, findGaps, sixMonthsBefore, type Gap } from '../gapBands'

// Daily candles with moving averages, and three lower panes, each showing an indicator
// picked from a list (volume, MACD, KDJ, RSI) whose parameters can be changed in place.
//   full      the stock's whole history from the local store (since listing), opening on the last year
//   fit       size the chart to the screen: candles and all three panes within one screen
//   end       last day to draw; markDate puts a marker on that day
const props = defineProps<{
  ticker: string; end?: string | null; markDate?: string | null; days?: number; full?: boolean; fit?: boolean
}>()

type Kind = 'VOL' | 'MACD' | 'KDJ' | 'RSI'
type Legend = [string, string, string][]   // [label, value, colour]
const KINDS: { value: Kind; label: string }[] = [
  { value: 'VOL', label: '成交量' },
  { value: 'MACD', label: 'MACD' },
  { value: 'KDJ', label: 'KDJ' },
  { value: 'RSI', label: 'RSI' },
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
const LINE3 = [C5, C10, '#9333ea']   // the three lines of MACD / KDJ / RSI
const RANGES: [string, number][] = [['3月', 63], ['1年', 250], ['3年', 750], ['全部', 0]]
const PANES = 3
const FIXED_HEIGHT = 900           // without ``fit``
const FOOT_ROOM = 52               // the line under the chart, the card's and the page's bottom padding
const DEFAULT_KINDS: Kind[] = ['VOL', 'MACD', 'KDJ']

// Indicator parameters, editable; each list is [label, min, max] per value.
const PARAM_SPEC: Record<Exclude<Kind, 'VOL'>, { names: string[]; defaults: number[] }> = {
  MACD: { names: ['快线', '慢线', '信号'], defaults: [12, 26, 9] },
  KDJ: { names: ['N', 'M1', 'M2'], defaults: [9, 3, 3] },
  RSI: { names: ['N1', 'N2', 'N3'], defaults: [6, 12, 24] },
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
const validParams = (v: unknown) =>
  !!v && typeof v === 'object' && (['MACD', 'KDJ', 'RSI'] as const).every((k) => {
    const p = (v as Record<string, unknown>)[k]
    return Array.isArray(p) && p.length === 3 && p.every((n) => Number.isInteger(n) && n >= 1 && n <= 250)
  })

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
// The gaps under the mouse (latest first) and where to show them.
const gapTip = ref<{ gaps: Gap[]; x: number; y: number; flip: boolean } | null>(null)
const DEFAULT_PARAMS: Record<'MACD' | 'KDJ' | 'RSI', number[]> = {
  MACD: [...PARAM_SPEC.MACD.defaults], KDJ: [...PARAM_SPEC.KDJ.defaults], RSI: [...PARAM_SPEC.RSI.defaults],
}
const params = reactive<Record<'MACD' | 'KDJ' | 'RSI', number[]>>(load(STORE.params, DEFAULT_PARAMS, validParams))
// What the settings panel edits, applied to ``params`` as soon as it is valid.
const draft = reactive<Record<'MACD' | 'KDJ' | 'RSI', (number | null)[]>>({
  MACD: [...params.MACD], KDJ: [...params.KDJ], RSI: [...params.RSI],
})
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

const bars = computed(() => data.value?.bars || [])
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
  }
}
const legends = computed(() => kinds.value.map((k) => legend(k)))
const title = (kind: Kind) => (kind === 'VOL' ? '' : `(${params[kind].join(',')})`)

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
  } else {
    lines(rsiData.value)
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
  gapList = []
  gapTip.value = null
  error.value = ''
  hoverIndex.value = null
  loading.value = true
  try {
    const k = await api.kline(props.ticker, props.end || undefined, props.days ?? 250, props.full ? 'snapshot' : 'vendor')
    if (!k.bars.length) throw new Error('没有行情数据')
    data.value = k
    indexByTime = new Map(k.bars.map((b, i) => [b.time, i]))
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
    candles.setData(k.bars.map((b) => ({ time: b.time as Time, open: b.open, high: b.high, low: b.low, close: b.close })))
    // Less headroom above the highest candle than the library's 20%.
    candles.priceScale().applyOptions({ scaleMargins: { top: 0.07, bottom: 0.04 } })
    candleSeries = candles
    gapBands = new GapBands()
    candles.attachPrimitive(gapBands)
    // Only the last six months' gaps, counted back from the last bar.
    const gaps = findGaps(k.bars, sixMonthsBefore(k.bars[k.bars.length - 1].time))
    gapCount.value = gaps.length
    gapList = gaps
    gapBands.setGaps(gaps)
    gapBands.setVisible(showGaps.value)
    PRICE_MAS.forEach(([, color], i) => line(color, 0).setData(points(priceMa.value[i])))
    if (props.markDate) {
      const at = [...k.bars].reverse().find((b) => b.time <= props.markDate!)
      if (at) {
        createSeriesMarkers(candles, [
          { time: at.time as Time, position: 'aboveBar', color: '#2563eb', shape: 'arrowDown', text: '分析日' },
        ])
      }
    }
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

function setKind(p: number, kind: Kind) {
  kinds.value[p] = kind
  if (editing.value === p && kind === 'VOL') editing.value = null
  save(STORE.kinds, kinds.value)
  drawPane(p)
}

// A parameter set is usable when every value is an integer from 1 to 250, and MACD's fast < slow.
function problem(kind: 'MACD' | 'KDJ' | 'RSI'): string {
  const v = draft[kind]
  if (v.some((n) => n === null || !Number.isInteger(n) || n < 1 || n > 250)) return '每个参数应为 1 到 250 的整数'
  if (kind === 'MACD' && (v[0] as number) >= (v[1] as number)) return '快线周期应小于慢线周期'
  return ''
}

// Applied as soon as the draft is valid: recompute, and redraw the panes showing that indicator.
watch(draft, () => {
  for (const kind of ['MACD', 'KDJ', 'RSI'] as const) {
    if (problem(kind) || draft[kind].every((n, i) => n === params[kind][i])) continue
    params[kind] = draft[kind].map(Number)
    save(STORE.params, params)
    kinds.value.forEach((k, p) => {
      if (k === kind) drawPane(p)
    })
  }
}, { deep: true })

watch(showGaps, (v) => {
  save('kline.gaps', v)
  gapBands?.setVisible(v)
  if (!v) gapTip.value = null
})

function reset(kind: 'MACD' | 'KDJ' | 'RSI') {
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
      <strong>{{ data?.name || ticker }} 日K线</strong>
      <template v-if="shown">
        <span class="muted num">{{ shown.time }}</span>
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
      <label v-if="bars.length" class="gap-toggle" :title="`最近半年相邻两日的跳空缺口：共 ${gapCount} 个`">
        <input v-model="showGaps" type="checkbox" /> 近半年缺口 {{ gapCount }}
      </label>
      <span v-if="full && bars.length" class="ranges">
        <button v-for="[label, n] in RANGES" :key="label" :class="{ on: range === n }" @click="showRange(n)">{{ label }}</button>
      </span>
    </div>
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
        <div v-for="(top, p) in paneTops" :key="p" class="lower" :style="{ top: `${top}px` }">
          <select :value="kinds[p]" class="pick" :aria-label="`副图${p + 1}指标`"
                  @change="setKind(p, ($event.target as HTMLSelectElement).value as Kind)">
            <option v-for="o in KINDS" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
          <button v-if="kinds[p] !== 'VOL'" class="gear" :class="{ on: editing === p }" :title="`${kinds[p]} 参数`"
                  @click="editing = editing === p ? null : p">
            <i class="pi pi-cog" />
          </button>
          <span class="muted small">{{ title(kinds[p]) }}</span>
          <span v-for="[label, value, color] in legends[p]" :key="label" class="num small" :style="{ color }">
            {{ label }}: {{ value }}
          </span>
          <div v-if="editing === p && kinds[p] !== 'VOL'" class="params">
            <template v-for="kind in [kinds[p] as 'MACD' | 'KDJ' | 'RSI']" :key="kind">
              <div class="params-title">{{ kind }} 参数 <span class="muted">（修改后立即生效）</span></div>
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
      {{ data.adjust }} · {{ bars[0].time }} 至 {{ bars[bars.length - 1].time }} · 共 {{ bars.length }} 根
      <template v-if="data.source === 'snapshot'">
        · 本地快照：base 至 {{ data.base_through || '—' }}<template v-if="data.after_base">，之后 {{ data.after_base }} 个交易日来自每日快照</template>
      </template>
      <template v-else> · 来源：AKShare / Yahoo 行情</template>
      <span v-if="data.note"> · {{ data.note }}</span>
      · 拖动平移，滚轮缩放 ·
      图表：<a href="https://www.tradingview.com/" target="_blank" rel="noopener">TradingView Lightweight Charts</a>
    </div>
  </div>
</template>

<style scoped>
.head { margin-bottom: 4px; gap: 10px; }
.mas { gap: 14px; font-size: 12px; margin-bottom: 6px; }
.spacer { flex: 1; }
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
.pick, .gear, .params { pointer-events: auto; }
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
