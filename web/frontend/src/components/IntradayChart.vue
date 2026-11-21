<script setup lang="ts">
// 分时 (days = 1: the latest day, with the 09:15–09:25 call auction before the open and the
// trade-by-trade list under the chart) and 五日 (days = 5): minute by minute: the price, the day's average price (均价)
// and the volume, against the close of the day before (昨收). The minutes run on without the lunch
// break or the nights between days; each day starts at its date on the axis.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ColorType, HistogramSeries, LineSeries, createChart, createSeriesMarkers,
  type IChartApi, type ISeriesApi, type ISeriesMarkersPluginApi, type MouseEventParams, type SeriesMarker, type Time,
} from 'lightweight-charts'
import { api, formatPct, formatYuan, type Auction, type Intraday, type Ticks } from '../api'
import type { MinuteHover } from '../kperiod'

const props = withDefaults(defineProps<{ code: string; height: number; days?: number }>(), { days: 5 })
const one = computed(() => props.days === 1)
// The minute under the mouse, for the page's card (null when the mouse is off the chart).
const emit = defineEmits<{ minute: [m: (MinuteHover & { change: number | null }) | null] }>()
const UP = '#e5484d'
const DOWN = '#1f9d55'
const el = ref<HTMLDivElement>()
const data = ref<Intraday | null>(null)
const error = ref('')
const loading = ref(false)
const hover = ref<number | null>(null)
let chart: IChartApi | null = null

// Each minute as a point: its day, clock time, and a timestamp the chart can order (read as UTC).
const minutePoints = computed(() => (data.value?.days || []).flatMap((d) => d.points.map((p) => ({ ...p, date: d.date, auc: false }))))
// 分时: the call auction (09:15–09:25, or only its 09:25 match when the minutes are not to be had)
// leads the day on the same line, so the two read as one.
const points = computed(() => {
  const pts = minutePoints.value
  const a = auction.value
  const day = data.value?.days[data.value.days.length - 1]?.date
  if (!one.value || !a || a.date !== day || !pts.length) return pts
  const pre = a.points.length ? a.points : a.match ? [{ time: a.match.time.slice(0, 5), price: a.match.price, volume: a.match.volume }] : []
  return [...pre.map((p) => ({ time: p.time, price: p.price, avg: null as number | null, volume: p.volume,
                               amount: p.price * p.volume, date: day, auc: true })), ...pts]
})
// 分时 only: the call auction and the trades, loaded after the chart (the trade list can take a while).
const auction = ref<Auction | null>(null)
const auctionError = ref('')
const ticks = ref<Ticks | null>(null)
const ticksError = ref('')
const ticksLoading = ref(false)
// The size filter (手): 0 every trade, a negative value "under", a positive one "at or over"; the
// bold size follows an "at or over" pick (500 手 otherwise).
const BIG_OPTIONS: { value: number; label: string }[] = [
  { value: 0, label: '全部成交' }, { value: -200, label: '小单 < 200 手' },
  ...[200, 300, 500, 800, 1500].map((n) => ({ value: n, label: `大单 ≥ ${n} 手` })),
]
const bigLots = ref(0)
const BIG = computed(() => (bigLots.value > 0 ? bigLots.value : 500) * 100)          // shares
// The rows the filter keeps, and their count and buy / sell totals (the heading follows the filter).
const filtered = computed(() => {
  const rows = ticks.value?.rows || []
  const n = bigLots.value * 100
  return n > 0 ? rows.filter((r) => r.volume >= n) : n < 0 ? rows.filter((r) => r.volume < -n) : rows
})
const summary = computed(() => {
  const s = { count: 0, buy: 0, buyN: 0, sell: 0, sellN: 0, auc: 0, aucN: 0 }
  for (const r of filtered.value) {
    s.count += 1
    if (r.side === '买') { s.buy += r.volume; s.buyN += 1 } else if (r.side === '卖') { s.sell += r.volume; s.sellN += 1 } else if (r.side === '竞价') { s.auc += r.volume; s.aucN += 1 }
  }
  return s
})
// Sorting by 成交价格 / 成交量 / 成交额: descending, then ascending, then back to time (latest first).
type SortKey = 'price' | 'volume' | 'amount'
const sortKey = ref<SortKey | null>(null)
const sortDir = ref<1 | -1>(-1)
function sortBy(k: SortKey) {
  if (sortKey.value !== k) {
    sortKey.value = k
    sortDir.value = -1
  } else if (sortDir.value === -1) sortDir.value = 1
  else sortKey.value = null
}
const arrow = (k: SortKey) => (sortKey.value !== k ? '⇅' : sortDir.value === -1 ? '↓' : '↑')
const shownTicks = computed(() => {
  const list = [...filtered.value]
  const k = sortKey.value
  if (!k) return list.reverse()   // the latest first
  const val = (r: { price: number; volume: number }) => (k === 'price' ? r.price : k === 'volume' ? r.volume : r.price * r.volume)
  return list.sort((a, b) => (val(a) - val(b)) * sortDir.value)
})

// 成交量分布: the trades by size, buy and sell. The bands follow this stock's own trade sizes (the
// 50 / 75 / 90 / 97 / 99.5th percentiles of the continuous session's trades, in 手, rounded to 1, 2,
// 3 or 5 × 10ⁿ), so a heavily traded and a thin stock both show a spread, not one crowded band.
function nice(x: number): number {
  if (x <= 1) return 1
  const p = 10 ** Math.floor(Math.log10(x))
  return [1, 2, 3, 5, 10].map((m) => m * p).reduce((a, b) => (Math.abs(b - x) < Math.abs(a - x) ? b : a))
}
const bands = computed(() => {
  const rows = ticks.value?.rows || []
  const cont = rows.filter((r) => r.time > '09:25:59' && r.time < '14:57:00').map((r) => r.volume / 100).sort((a, b) => a - b)
  if (!cont.length) return []
  const q = (f: number) => cont[Math.min(cont.length - 1, Math.floor(f * cont.length))]
  const edges = [...new Set([0.5, 0.75, 0.9, 0.97, 0.995].map((f) => nice(q(f))))].sort((a, b) => a - b)
  const bounds = [0, ...edges, Infinity]
  const out = bounds.slice(0, -1).map((lo, i) => {
    const hi = bounds[i + 1]
    return { label: i === 0 ? `< ${hi} 手` : hi === Infinity ? `≥ ${lo} 手` : `${lo} – ${hi} 手`,
             lo, hi, buy: 0, sell: 0, buyN: 0, sellN: 0, other: 0 }
  })
  for (const r of rows) {
    const l = r.volume / 100
    const b = out.find((x) => l >= x.lo && l < x.hi)
    if (!b) continue
    if (r.side === '买') { b.buy += l; b.buyN += 1 } else if (r.side === '卖') { b.sell += l; b.sellN += 1 } else b.other += l
  }
  return out
})
const bandMax = computed(() => Math.max(1, ...bands.value.map((b) => Math.max(b.buy, b.sell))))
const bandTotal = computed(() => bands.value.reduce((a, b) => ({ buy: a.buy + b.buy, sell: a.sell + b.sell,
  buyN: a.buyN + b.buyN, sellN: a.sellN + b.sellN }), { buy: 0, sell: 0, buyN: 0, sellN: 0 }))
// The two pages (成交明细, 成交量分布) side by side: scroll or swipe right, or pick one.
const pagesEl = ref<HTMLDivElement>()
const page = ref(0)
function goPage(i: number) {
  pagesEl.value?.scrollTo({ left: i * (pagesEl.value?.clientWidth || 0), behavior: 'smooth' })
}
function onPagesScroll() {
  const el = pagesEl.value
  if (el) page.value = Math.round(el.scrollLeft / Math.max(1, el.clientWidth))
}
const lots = (v: number) => Math.round(v / 100)
async function loadExtras() {
  if (!one.value) return
  auction.value = null
  auctionError.value = ''
  ticks.value = null
  ticksError.value = ''
  ticksLoading.value = true
  api.stockAuction(props.code).then((a) => {
    auction.value = a
    fill()                                       // the auction joins the line on its left
  }).catch((e) => { auctionError.value = e instanceof Error ? e.message : String(e) })
  try {
    ticks.value = await api.stockTicks(props.code)
  } catch (e) {
    ticksError.value = e instanceof Error ? e.message : String(e)
  } finally {
    ticksLoading.value = false
  }
}

const stamp = (date: string, hm: string) => Date.UTC(+date.slice(0, 4), +date.slice(5, 7) - 1, +date.slice(8, 10),
  +hm.slice(0, 2), +hm.slice(3, 5)) / 1000
const shown = computed(() => points.value[hover.value ?? points.value.length - 1] || null)
const change = (p: number | null | undefined) =>
  p === null || p === undefined || !data.value?.prev_close ? null : (p / data.value.prev_close - 1) * 100
// Volume axes in 手 (lots), as everywhere else on the page: 1.2万手, not 120K shares.
const lotsAxis = { type: 'custom' as const, minMove: 1,
                   formatter: (v: number) => (v >= 1e4 ? `${(v / 1e4).toFixed(v >= 1e5 ? 0 : 1)}万手` : `${Math.round(v)}手`) }
const vol = (v: number) => (v >= 1e8 ? `${(v / 1e8).toFixed(2)}亿` : v >= 1e4 ? `${(v / 1e4).toFixed(1)}万` : v.toFixed(0))
// Each day's change against the day before's close (the first against 昨收).
const dayChanges = computed(() => {
  const ds = data.value?.days || []
  return ds.map((d, i) => {
    const base = i === 0 ? data.value?.prev_close : ds[i - 1].close
    return { date: d.date, close: d.close, pct: base ? (d.close / base - 1) * 100 : null }
  })
})

function fmtTime(t: Time): string {
  const d = new Date((t as number) * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`
}

// The series, filled from points (again when the auction arrives): the line purple over the call
// auction and blue after the open, one line; the auction's volume bars purple too.
const AUC = '#7c3aed'
let priceSeries: ISeriesApi<'Line'> | null = null
let avgSeries: ISeriesApi<'Line'> | null = null
let barSeries: ISeriesApi<'Histogram'> | null = null
let priceMarkers: ISeriesMarkersPluginApi<Time> | null = null
// 分时: the price axis symmetric about 昨收 (as far up as down, as market terminals draw it), with
// the change from 昨收 on a left axis and at the top and bottom edges.
let pctSeries: ISeriesApi<'Line'> | null = null
const symmetric = ref<{ base: number; span: number } | null>(null)      // span: the half-range, a fraction
const edges = ref<{ top: number; bottom: number } | null>(null)        // the edge labels' y (px)
const MARGIN = 0.04                                                       // the scales' top / bottom margins
function placeEdges() {
  requestAnimationFrame(() => {
    if (!chart || !symmetric.value) {
      edges.value = null
      return
    }
    const h = chart.paneSize(0).height
    edges.value = { top: h * MARGIN, bottom: h * (1 - MARGIN) }
  })
}
let index = new Map<number, number>()
function fill() {
  if (!chart || !priceSeries || !avgSeries || !barSeries) return
  const pts = points.value
  priceSeries.setData(pts.map((p) => ({ time: stamp(p.date, p.time) as Time, value: p.price, color: p.auc ? AUC : undefined })))
  avgSeries.setData(pts.filter((p) => p.avg !== null).map((p) => ({ time: stamp(p.date, p.time) as Time, value: p.avg as number })))
  barSeries.setData(pts.map((p, i) => ({ time: stamp(p.date, p.time) as Time, value: p.volume / 100,
                                         color: p.auc ? AUC : i && p.price < pts[i - 1].price ? DOWN : UP })))
  index = new Map(pts.map((p, i) => [stamp(p.date, p.time), i]))
  // 分时: symmetric about 昨收 (the close before), as the market terminals draw it.
  const base = one.value ? (data.value?.prev_close ?? minutePoints.value[0]?.price ?? null) : null
  if (base && pctSeries) {
    const prices = pts.map((p) => p.price)
    const far = Math.max(...prices.map((v) => Math.abs(v / base - 1)), 0.002)
    const span = far * 1.05
    symmetric.value = { base, span }
    const range = { priceRange: { minValue: base * (1 - span), maxValue: base * (1 + span) } }
    priceSeries.applyOptions({ autoscaleInfoProvider: () => range })
    avgSeries.applyOptions({ autoscaleInfoProvider: () => range })
    pctSeries.applyOptions({ autoscaleInfoProvider: () => ({ priceRange: { minValue: -span * 100, maxValue: span * 100 } }) })
    pctSeries.setData(pts.map((p) => ({ time: stamp(p.date, p.time) as Time, value: (p.price / base - 1) * 100 })))
  } else {
    symmetric.value = null
  }
  placeEdges()
  const aucPts = pts.filter((p) => p.auc)
  const marks: SeriesMarker<Time>[] = []
  const at920 = aucPts.find((p) => p.time >= '09:20')
  if (at920 && aucPts.length > 1) {
    marks.push({ time: stamp(at920.date, at920.time) as Time, position: 'aboveBar', shape: 'arrowDown', color: '#b45309',
                 text: '9:20' })
  }
  const open = aucPts[aucPts.length - 1]
  if (open) marks.push({ time: stamp(open.date, open.time) as Time, position: 'belowBar', shape: 'arrowUp', color: AUC, text: '开盘' })
  priceMarkers?.setMarkers(marks)
  // A little room on the left, so the auction's first minutes and their marks are not on the edge.
  if (aucPts.length) chart.timeScale().setVisibleLogicalRange({ from: -4, to: pts.length + 1 })
  else chart.timeScale().fitContent()
}

async function draw() {
  if (!el.value) return
  chart?.remove()
  chart = null
  error.value = ''
  loading.value = true
  try {
    data.value = await api.stockIntraday(props.code, props.days)
    const pts = minutePoints.value
    if (!pts.length) throw new Error('没有分时数据')
    const firstOfDay = new Set(data.value.days.map((d) => stamp(d.date, d.points[0]?.time || '09:30')))
    chart = createChart(el.value, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: '#ffffff' }, textColor: '#4b5563',
                panes: { separatorColor: '#d1d5db' }, attributionLogo: false },
      grid: { vertLines: { color: '#f1f3f6' }, horzLines: { color: '#f1f3f6' } },
      // 分时: the left axis (change from 昨收) exists from the start: the library builds its axes
      // with the chart, so turning one on afterwards breaks the layout.
      rightPriceScale: { borderColor: '#e3e7ec', ...(one.value ? { scaleMargins: { top: MARGIN, bottom: MARGIN } } : {}) },
      leftPriceScale: { visible: one.value, borderColor: '#e3e7ec', scaleMargins: { top: MARGIN, bottom: MARGIN } },
      timeScale: {
        borderColor: '#e3e7ec', timeVisible: true,
        // A day's first minute shows its date; the others the clock time.
        tickMarkFormatter: (t: Time) => (!one.value && firstOfDay.has(t as number) ? fmtTime(t).slice(0, 5) : fmtTime(t).slice(6)),
      },
      localization: { locale: 'zh-CN', timeFormatter: fmtTime },
    })
    priceSeries = chart.addSeries(LineSeries, { color: '#2563eb', lineWidth: 2, priceLineVisible: false, lastValueVisible: true })
    avgSeries = chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
                                              crosshairMarkerVisible: false })
    if (data.value.prev_close) {
      priceSeries.createPriceLine({ price: data.value.prev_close, color: '#9ca3af', lineWidth: 1, lineStyle: 2,
                                    axisLabelVisible: true, title: '昨收' })
    }
    barSeries = chart.addSeries(HistogramSeries, { priceFormat: lotsAxis, priceLineVisible: false,
                                                   lastValueVisible: false }, 1)
    // 分时: an invisible line of the change from 昨收 on the left axis (same margins as the right,
    // and a range mirroring the price's, so the two axes line up).
    pctSeries = null
    if (one.value) {
      pctSeries = chart.addSeries(LineSeries, { color: 'rgba(0,0,0,0)', lineWidth: 1, priceScaleId: 'left', priceLineVisible: false,
                                                lastValueVisible: false, crosshairMarkerVisible: false,
                                                priceFormat: { type: 'custom', minMove: 0.01,
                                                               formatter: (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(2)}%` } })
    }
    priceMarkers = createSeriesMarkers(priceSeries, [])
    chart.panes()[0].setStretchFactor(3)
    chart.panes()[1].setStretchFactor(1)
    chart.subscribeCrosshairMove((e: MouseEventParams) => {
      hover.value = e.time !== undefined ? (index.get(e.time as number) ?? null) : null
      const p = hover.value === null ? null : points.value[hover.value]
      emit('minute', p ? { date: p.date, time: p.time, price: p.price, avg: p.avg, volume: p.volume, amount: p.amount,
                           change: change(p.price) } : null)
    })
    fill()
  } catch (e) {
    data.value = null
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function reload() {
  await draw()
  loadExtras()
}
onMounted(reload)
watch(() => [props.code, props.days], reload)
onBeforeUnmount(() => chart?.remove())
defineExpose({ reload })
</script>

<template>
  <div>
    <div class="row head">
      <template v-if="shown">
        <span class="muted num">{{ shown.date }} {{ shown.time }}</span>
        <span :class="['num', (change(shown.price) ?? 0) > 0 ? 'up' : (change(shown.price) ?? 0) < 0 ? 'down' : '']">
          价 {{ shown.price.toFixed(2) }} {{ formatPct(change(shown.price)) }}
        </span>
        <span class="num" style="color: #d97706">均价 {{ shown.avg?.toFixed(2) ?? '—' }}</span>
        <span class="num muted">量 {{ vol(shown.volume / 100) }}手 · 额 {{ formatYuan(shown.amount) }}</span>
        <span v-if="data?.prev_close" class="num muted">昨收 {{ data.prev_close.toFixed(2) }}</span>
      </template>
      <span v-if="loading" class="muted"><i class="pi pi-spin pi-spinner" /> 加载分时</span>
      <span class="spacer" />
      <button class="refresh" title="刷新（分时数据缓存 1 分钟，成交明细 2 分钟）" @click="reload"><i class="pi pi-refresh" /></button>
    </div>
    <!-- 分时: the call auction's result before the chart. -->
    <div v-if="one" class="row auction small">
      <b>集合竞价</b>
      <template v-if="auction?.match">
        <span class="num">{{ auction.match.time }} 开盘价 <b :class="(change(auction.match.price) ?? 0) >= 0 ? 'up' : 'down'">{{ auction.match.price.toFixed(2) }}</b>
          （{{ formatPct(change(auction.match.price)) }}）</span>
        <span class="num">成交 {{ lots(auction.match.volume).toLocaleString() }} 手 · 约 {{ formatYuan(auction.match.price * auction.match.volume) }}</span>
        <span class="muted">来源：{{ auction.source }}</span>
        <span v-if="auction.points.length" class="muted">图中左侧紫色段为 9:15–9:25 集合竞价走势（每分钟的虚拟匹配价，终点为 9:25 实际撮合价；竞价期间没有成交，只有 9:25 撮合有量），与分时连成一条线；「9:20」之后不能撤单，「开盘」为 9:25 撮合价</span>
        <span v-else class="muted">（9:15–9:25 竞价走势需要东方财富的盘前分时，暂不可用；图中左侧只有 9:25 撮合价）</span>
      </template>
      <span v-else-if="auctionError" class="muted">暂不可用：{{ auctionError }}</span>
      <span v-else class="muted"><i class="pi pi-spin pi-spinner" /> 加载中</span>
    </div>
    <div v-if="dayChanges.length && !one" class="row days num">
      <span v-for="d in dayChanges" :key="d.date">{{ d.date.slice(5) }}
        <b :class="(d.pct ?? 0) > 0 ? 'up' : (d.pct ?? 0) < 0 ? 'down' : ''">{{ formatPct(d.pct) }}</b></span>
    </div>
    <div v-if="error" class="muted error">分时加载失败：{{ error }}</div>
    <div class="chart-frame">
      <div ref="el" class="chart" :style="{ height: `${height}px` }" />
      <template v-if="one && symmetric && edges">
        <div class="edge up" :style="{ top: `${edges.top}px` }">
          +{{ (symmetric.span * 100).toFixed(2) }}% · {{ (symmetric.base * (1 + symmetric.span)).toFixed(2) }}
        </div>
        <div class="edge down" :style="{ top: `${edges.bottom}px` }">
          −{{ (symmetric.span * 100).toFixed(2) }}% · {{ (symmetric.base * (1 - symmetric.span)).toFixed(2) }}
        </div>
      </template>
    </div>
    <!-- 分时: the trades one by one, the latest first. -->
    <div v-if="one" class="ticks">
      <div class="row ticks-head small">
        <b>成交明细</b>
        <template v-if="ticks">
          <span class="muted">{{ ticks.date }}</span>
          <label class="big">只看
            <select v-model.number="bigLots" class="big-select">
              <option v-for="o in BIG_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </label>
          <span class="muted" title="免费行情的成交明细是每 3 秒一次的快照：每一行是这 3 秒内全部成交的合计，不是单笔委托；各家软件的快照时刻不同（如 09:36:16 与 09:36:17），单行数量无法一一对应，但全天合计一致">来源：{{ ticks.source }} · 每行为 3 秒内成交合计 ⓘ</span>
        </template>
        <span v-else-if="ticksLoading" class="muted"><i class="pi pi-spin pi-spinner" /> 加载成交明细（新浪逐页抓取时约需 15 秒）</span>
        <span v-else-if="ticksError" class="muted">暂不可用：{{ ticksError }}</span>
      </div>
      <div v-if="ticks" class="row ticks-sum small num">
        <span class="muted">共 {{ summary.count.toLocaleString() }} 笔<template v-if="bigLots">（全天 {{ ticks.count.toLocaleString() }} 笔）</template></span>
        <span class="up">主动买 {{ lots(summary.buy).toLocaleString() }} 手 · {{ summary.buyN.toLocaleString() }} 笔</span>
        <span class="down">主动卖 {{ lots(summary.sell).toLocaleString() }} 手 · {{ summary.sellN.toLocaleString() }} 笔</span>
        <span :class="summary.buy >= summary.sell ? 'up' : 'down'" title="主动买手数 − 主动卖手数（不含集合竞价）">净量 {{ (summary.buy >= summary.sell ? '+' : '') + lots(summary.buy - summary.sell).toLocaleString() }} 手</span>
        <span v-if="summary.aucN" class="auc-text" title="09:25 开盘与 15:00 收盘集合竞价：买卖双方按同一价格撮合，没有主动方，不计入主动买、主动卖和净量">竞价 {{ summary.aucN }} 笔 · {{ lots(summary.auc).toLocaleString() }} 手（不计入主动买卖）</span>
</div>
      <div v-if="ticks" class="page-tabs">
        <button :class="{ on: page === 0 }" @click="goPage(0)">成交明细</button>
        <button :class="{ on: page === 1 }" @click="goPage(1)">成交量分布 →</button>
        <span class="muted small">可向右滑动查看成交量分布</span>
      </div>
      <div v-if="ticks" ref="pagesEl" class="pages" @scroll.passive="onPagesScroll">
        <div class="page-pane ticks-wrap">
          <table class="ticks-table num">
            <thead><tr>
              <th>时间</th>
              <th class="r sort" @click="sortBy('price')">成交价格 {{ arrow('price') }}</th>
              <th class="r">涨跌</th>
              <th class="r sort" @click="sortBy('volume')">成交量（手） {{ arrow('volume') }}</th>
              <th class="r sort" @click="sortBy('amount')">成交额 {{ arrow('amount') }}</th>
              <th>性质</th>
            </tr></thead>
            <tbody>
              <tr v-for="(t, i) in shownTicks" :key="i" :class="{ auc: t.side === '竞价', bigrow: t.volume >= BIG }">
                <td>{{ t.time }}<span v-if="t.side === '竞价'" class="tag-auc">{{ t.time <= '09:25:59' ? '开盘竞价' : '收盘竞价' }}</span></td>
                <td class="r" :class="(change(t.price) ?? 0) > 0 ? 'up' : (change(t.price) ?? 0) < 0 ? 'down' : ''">{{ t.price.toFixed(2) }}</td>
                <td class="r" :class="(change(t.price) ?? 0) > 0 ? 'up' : (change(t.price) ?? 0) < 0 ? 'down' : ''">{{ formatPct(change(t.price)) }}</td>
                <td class="r">{{ lots(t.volume).toLocaleString() }}</td>
                <td class="r muted">{{ formatYuan(t.price * t.volume) }}</td>
                <td :class="t.side === '买' ? 'up' : t.side === '卖' ? 'down' : t.side === '竞价' ? 'auc-text' : 'muted'">{{ t.side }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="page-pane ticks-wrap">
          <table class="ticks-table num dist">
            <thead><tr><th>成交量分布</th><th>买</th><th>卖</th><th class="r">净量（买 − 卖）</th></tr></thead>
            <tbody>
              <tr v-for="b in bands" :key="b.label">
                <td>{{ b.label }}</td>
                <td>
                  <div class="bar-cell"><span class="bar up-bar" :style="{ width: `${(b.buy / bandMax) * 100}%` }" /></div>
                  <span class="up">{{ Math.round(b.buy).toLocaleString() }} 手</span>
                  <span class="muted">（{{ b.buyN.toLocaleString() }} 笔，{{ bandTotal.buy ? ((b.buy / bandTotal.buy) * 100).toFixed(1) : 0 }}%）</span>
                </td>
                <td>
                  <div class="bar-cell"><span class="bar down-bar" :style="{ width: `${(b.sell / bandMax) * 100}%` }" /></div>
                  <span class="down">{{ Math.round(b.sell).toLocaleString() }} 手</span>
                  <span class="muted">（{{ b.sellN.toLocaleString() }} 笔，{{ bandTotal.sell ? ((b.sell / bandTotal.sell) * 100).toFixed(1) : 0 }}%）</span>
                </td>
                <td class="r" :class="b.buy - b.sell >= 0 ? 'up' : 'down'">{{ (b.buy - b.sell >= 0 ? '+' : '') + Math.round(b.buy - b.sell).toLocaleString() }} 手</td>
              </tr>
              <tr class="total">
                <td>合计</td>
                <td class="up">{{ Math.round(bandTotal.buy).toLocaleString() }} 手（{{ bandTotal.buyN.toLocaleString() }} 笔）</td>
                <td class="down">{{ Math.round(bandTotal.sell).toLocaleString() }} 手（{{ bandTotal.sellN.toLocaleString() }} 笔）</td>
                <td class="r" :class="bandTotal.buy - bandTotal.sell >= 0 ? 'up' : 'down'">{{ (bandTotal.buy - bandTotal.sell >= 0 ? '+' : '') + Math.round(bandTotal.buy - bandTotal.sell).toLocaleString() }} 手</td>
              </tr>
            </tbody>
          </table>
          <div class="muted small dist-note">区间按这只股票当天连续竞价的单笔成交量分档（第 50 / 75 / 90 / 97 / 99.5 百分位，取整）；买 / 卖为主动买入 / 主动卖出，中性成交和开盘、收盘集合竞价（没有主动方）都不计入。</div>
        </div>
      </div>
    </div>
    <div v-if="data" class="muted foot">
      {{ one ? '分时' : '五日分时' }} · 蓝线：成交价；橙线：当日均价（累计成交额 ÷ 成交量）；虚线：{{ dayChanges[0]?.date }} 前一日收盘（昨收）·
      分时图数据：{{ data.source }}，缓存 1 分钟（成交明细的来源见上方） · 午休与隔夜不占位置
    </div>
  </div>
</template>

<style scoped>
.head { margin-bottom: 4px; gap: 10px; }
.days { gap: 14px; font-size: 12px; margin-bottom: 6px; color: var(--muted); }
.spacer { flex: 1; }
.chart { width: 100%; }
.chart-frame { position: relative; }
/* The range's top and bottom: the change from 昨收 and the price there. */
.edge { position: absolute; z-index: 4; right: 72px; transform: translateY(-50%); font-size: 11px; font-weight: 600; padding: 0 4px;
        background: rgba(255, 255, 255, 0.85); border-radius: 3px; pointer-events: none; font-variant-numeric: tabular-nums; }
.edge.up { color: var(--up); }
.edge.down { color: var(--down); }
.refresh { border: 1px solid var(--border); background: #fff; border-radius: 4px; padding: 2px 6px; cursor: pointer; color: var(--muted); }
.foot { margin-top: 6px; font-size: 12px; }
.small { font-size: 12px; }
.auction { gap: 12px; margin-bottom: 6px; padding: 4px 8px; background: #f8fafc; border-radius: 4px; flex-wrap: wrap; }
.ticks { margin-top: 10px; }
.ticks-head { gap: 12px; margin-bottom: 2px; flex-wrap: wrap; }
.ticks-sum { gap: 16px; margin-bottom: 4px; flex-wrap: wrap; }
.big { display: inline-flex; align-items: center; gap: 4px; }
.big-select { font: inherit; font-size: 12px; padding: 1px 4px; border: 1px solid var(--border); border-radius: 4px; background: #fff; }
.page-tabs { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
.page-tabs button { border: 1px solid var(--border); background: #fff; border-radius: 4px; padding: 2px 10px; cursor: pointer; font: inherit; font-size: 12px; color: var(--muted); }
.page-tabs button.on { background: #2563eb; color: #fff; border-color: #2563eb; }
.pages { display: flex; overflow-x: auto; scroll-snap-type: x mandatory; gap: 12px; scrollbar-width: thin; }
.page-pane { flex: 0 0 100%; scroll-snap-align: start; }
.sort { cursor: pointer; user-select: none; }
.sort:hover { color: #2563eb; }
.dist td { vertical-align: middle; padding: 6px 8px; }
.bar-cell { display: inline-block; width: 120px; height: 8px; background: #f1f3f6; border-radius: 4px; margin-right: 8px; vertical-align: middle; overflow: hidden; }
.bar { display: block; height: 100%; }
.up-bar { background: var(--up); }
.down-bar { background: var(--down); }
.dist .total td { font-weight: 600; border-top: 1px solid var(--border); }
.dist-note { padding: 6px 8px; }
.ticks-wrap { max-height: 360px; overflow-y: auto; border: 1px solid var(--border); border-radius: 6px; }
.ticks-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.ticks-table th { position: sticky; top: 0; background: #f8fafc; text-align: left; font-weight: 500; color: var(--muted); padding: 4px 8px; }
.ticks-table td { padding: 2px 8px; border-top: 1px solid #f1f3f6; white-space: nowrap; }
.ticks-table .r { text-align: right; }
.ticks-table tr.auc { background: #fefce8; }
.ticks-table tr.bigrow td { font-weight: 600; }
.auc-text { color: #b45309; font-weight: 600; }
.tag-auc { margin-left: 6px; font-size: 10px; padding: 0 4px; border-radius: 3px; background: #fde68a; color: #92400e; }
.error { padding: 8px 0; }
</style>
