<script setup lang="ts">
// Under the market table, for the day shown:
//   the spread of changes, the limit board (连板天梯) and the industries ranked;
// and over the day, 60 trading days, six months or a year up to it, each with its own span:
//   rises and falls, limit moves, the median stock's change (赚钱效应), the indexes against
//   the median stock with the advance-decline line, and the amount traded.
import { computed, ref, watch, type Ref } from 'vue'
import Select from 'primevue/select'
import { api, type MarketDayStats, type MarketRow, type MarketStats, type StatsRange } from '../api'
import LineChart, { type Line } from './LineChart.vue'
import LimitBoard from './LimitBoard.vue'
import IndustryBoard from './IndustryBoard.vue'

const props = defineProps<{ rows: MarketRow[]; date: string | null }>()
const emit = defineEmits<{ industry: [name: string] }>()

const UP = '#e5484d'
const DOWN = '#1f9d55'
const FLAT = '#9aa4b2'
const INK = '#111827'
const INDEX_COLORS: Record<string, string> = {
  上证指数: '#2563eb', 沪深300: '#7c3aed', 中证500: '#db2777', 中证1000: '#0891b2',
  创业板指: '#f59e0b', 创业板综: '#a16207', 科创综指: '#65a30d',
}

// ---- The day's spread: by size of change, falls on the left, rises on the right ----
// A change sits in a band by its size: 3% in 0–3, 7% in 5–7, 10% in 7–10, 10.02% in >10.
const BANDS: { label: string; side: 'down' | 'flat' | 'up'; test: (p: number) => boolean }[] = [
  { label: '>10%', side: 'down', test: (p) => p < -10 },
  { label: '10~7%', side: 'down', test: (p) => p >= -10 && p < -7 },
  { label: '7~5%', side: 'down', test: (p) => p >= -7 && p < -5 },
  { label: '5~3%', side: 'down', test: (p) => p >= -5 && p < -3 },
  { label: '3~0%', side: 'down', test: (p) => p >= -3 && p < 0 },
  { label: '0', side: 'flat', test: (p) => p === 0 },
  { label: '0~3%', side: 'up', test: (p) => p > 0 && p <= 3 },
  { label: '3~5%', side: 'up', test: (p) => p > 3 && p <= 5 },
  { label: '5~7%', side: 'up', test: (p) => p > 5 && p <= 7 },
  { label: '7~10%', side: 'up', test: (p) => p > 7 && p <= 10 },
  { label: '>10%', side: 'up', test: (p) => p > 10 },
]
const SIDE = { down: { name: '跌', color: DOWN }, flat: { name: '平', color: FLAT }, up: { name: '涨', color: UP } }

const spread = computed(() => {
  const pcts = props.rows.map((r) => r.pct_chg).filter((p): p is number => typeof p === 'number' && !Number.isNaN(p))
  const counts = BANDS.map((b) => pcts.filter(b.test).length)
  const max = Math.max(1, ...counts)
  return {
    total: pcts.length,
    up: pcts.filter((p) => p > 0).length,
    down: pcts.filter((p) => p < 0).length,
    flat: pcts.filter((p) => p === 0).length,
    bars: BANDS.map((b, i) => ({ ...b, count: counts[i], h: counts[i] / max })),
  }
})
const pctOf = (n: number, total: number) => (total ? `${((n / total) * 100).toFixed(1)}%` : '—')
const signed = (v: number, d = 2) => `${v > 0 ? '+' : ''}${v.toFixed(d)}%`

// ---- Spans: one picker per card, remembered in this browser ----
const RANGES: { value: StatsRange; label: string }[] = [
  { value: '1d', label: '当日' }, { value: '60d', label: '近60天' }, { value: '6m', label: '半年' }, { value: '1y', label: '一年' },
]
function rangeRef(key: string): Ref<StatsRange> {
  let v: StatsRange = '60d'
  try {
    const s = localStorage.getItem(key)
    if (RANGES.some((r) => r.value === s)) v = s as StatsRange
  } catch {
    /* storage blocked: the default */
  }
  const r = ref<StatsRange>(v)
  watch(r, (x) => {
    try {
      localStorage.setItem(key, x)
    } catch {
      /* storage blocked */
    }
  })
  return r
}

// One request per (span, day), shared by the cards.
const cache = new Map<string, Promise<MarketStats>>()
function fetchStats(range: StatsRange, end: string): Promise<MarketStats> {
  const key = `${range}|${end}`
  if (!cache.has(key)) {
    const p = api.marketStats(range, end)
    p.catch(() => cache.delete(key))
    cache.set(key, p)
  }
  return cache.get(key)!
}

function useStats(key: string) {
  const range = rangeRef(key)
  const data = ref<MarketStats | null>(null)
  const loading = ref(false)
  const error = ref('')
  watch([range, () => props.date], async ([r, d]) => {
    if (!d) return
    loading.value = true
    error.value = ''
    try {
      const s = await fetchStats(r, d)
      if (range.value === r && props.date === d) data.value = s
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }, { immediate: true })
  const days = computed<MarketDayStats[]>(() => data.value?.days || [])
  return { range, data, loading, error, days }
}
const avg = (days: MarketDayStats[], f: (d: MarketDayStats) => number) =>
  days.length ? days.reduce((a, d) => a + f(d), 0) / days.length : 0
const series = (days: MarketDayStats[], f: (d: MarketDayStats) => number) => days.map((d) => ({ time: d.date, value: f(d) }))

// ---- Rises and falls ----
const trend = useStats('market.trendRange')
const trendLines = computed<Line[]>(() => [
  { name: '上涨家数', color: UP, points: series(trend.days.value, (d) => d.up) },
  { name: '下跌家数', color: DOWN, points: series(trend.days.value, (d) => d.down) },
  { name: '平盘家数', color: FLAT, points: series(trend.days.value, (d) => d.flat) },
])
const trendSummary = computed(() => {
  const days = trend.days.value
  if (!days.length) return null
  return {
    n: days.length, start: days[0].date, end: days[days.length - 1].date, last: days[days.length - 1],
    upDays: days.filter((d) => d.up > d.down).length, downDays: days.filter((d) => d.up < d.down).length,
    avgUp: Math.round(avg(days, (d) => d.up)), avgDown: Math.round(avg(days, (d) => d.down)),
    avgFlat: Math.round(avg(days, (d) => d.flat)),
  }
})

// ---- Limit moves ----
const limits = useStats('market.limitRange')
const limitLines = computed<Line[]>(() => [
  { name: '涨停', color: UP, points: series(limits.days.value, (d) => d.limit_up) },
  { name: '跌停', color: DOWN, points: series(limits.days.value, (d) => d.limit_down) },
  { name: '炸板', color: '#f59e0b', points: series(limits.days.value, (d) => d.broken) },
])
const limitSummary = computed(() => {
  const days = limits.days.value
  if (!days.length) return null
  const touched = days.reduce((a, d) => a + d.limit_up + d.broken, 0)
  const top = days.reduce((a, d) => (d.limit_up > a.limit_up ? d : a))
  const bottom = days.reduce((a, d) => (d.limit_down > a.limit_down ? d : a))
  return {
    n: days.length, last: days[days.length - 1],
    avgUp: avg(days, (d) => d.limit_up).toFixed(0), avgDown: avg(days, (d) => d.limit_down).toFixed(0),
    brokenRate: touched ? ((days.reduce((a, d) => a + d.broken, 0) / touched) * 100).toFixed(1) : '—',
    top, bottom,
  }
})

// ---- 赚钱效应: the median stock's change, day by day ----
const effect = useStats('market.effectRange')
const effectLines = computed<Line[]>(() => [{
  name: '个股涨幅中位数', color: INK, bars: true,
  points: effect.days.value.filter((d) => d.median !== null)
    .map((d) => ({ time: d.date, value: d.median as number, color: (d.median as number) >= 0 ? UP : DOWN })),
}])
const effectSummary = computed(() => {
  const days = effect.days.value.filter((d) => d.median !== null)
  if (!days.length) return null
  const m = days.map((d) => d.median as number)
  return {
    n: days.length, last: m[m.length - 1],
    positive: m.filter((x) => x > 0).length,
    mean: m.reduce((a, x) => a + x, 0) / m.length,
    total: (m.reduce((a, x) => a * (1 + x / 100), 1) - 1) * 100,
    upShare: avg(days, (d) => (d.total ? (d.up / d.total) * 100 : 0)),
  }
})

// ---- The indexes against the median stock, and the advance-decline line ----
// Each line starts at 0% on the trading day before the span (the median stock compounds its
// daily median change from there); the advance-decline line adds up rises minus falls.
const versus = useStats('market.indexRange')
const versusLines = computed<Line[]>(() => {
  const s = versus.data.value
  if (!s) return []
  const lines: Line[] = Object.entries(s.indexes).filter(([, pts]) => pts.length).map(([name, pts]) => ({
    name, color: INDEX_COLORS[name] || FLAT,
    points: pts.map((p) => ({ time: p.date, value: (p.close / pts[0].close - 1) * 100 })),
  }))
  let f = 1
  const base = s.index_base < (s.days[0]?.date || '') ? [{ time: s.index_base, value: 0 }] : []
  lines.push({
    name: '个股中位数', color: INK,
    points: [...base, ...s.days.map((d) => {
      f *= 1 + (d.median ?? 0) / 100
      return { time: d.date, value: (f - 1) * 100 }
    })],
  })
  return lines
})
const adlLines = computed<Line[]>(() => {
  const s = versus.data.value
  if (!s) return []
  let sum = 0
  const base = s.index_base < (s.days[0]?.date || '') ? [{ time: s.index_base, value: 0 }] : []
  return [{
    name: '腾落线（累计上涨−下跌家数）', color: UP,
    points: [...base, ...s.days.map((d) => ({ time: d.date, value: (sum += d.up - d.down) }))],
  }]
})
// The summary in rows: large caps, the growth boards, mid and small caps, the median stock. A
// click on one hides or shows its line; which are hidden is remembered in this browser.
const INDEX_ROWS = [['上证指数', '沪深300'], ['创业板综', '科创综指', '创业板指'], ['中证500', '中证1000'], ['个股中位数']]
const HIDDEN_KEY = 'market.indexHidden'
const hidden = ref<string[]>((() => {
  try {
    const v = JSON.parse(localStorage.getItem(HIDDEN_KEY) || '[]')
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []
  } catch {
    return []
  }
})())
watch(hidden, (v) => {
  try {
    localStorage.setItem(HIDDEN_KEY, JSON.stringify(v))
  } catch {
    /* storage blocked */
  }
})
function toggleLine(name: string) {
  hidden.value = hidden.value.includes(name) ? hidden.value.filter((x) => x !== name) : [...hidden.value, name]
}
const shownVersusLines = computed(() => versusLines.value.filter((l) => !hidden.value.includes(l.name)))
const versusSummary = computed(() => {
  const lines = versusLines.value
  if (!lines.length) return null
  const last = (l: Line) => l.points[l.points.length - 1]?.value ?? 0
  const byName = new Map(lines.map((l) => [l.name, { name: l.name, color: l.color, value: last(l) }]))
  const listed = new Set(INDEX_ROWS.flat())
  const rows = INDEX_ROWS.map((r) => r.flatMap((n) => byName.get(n) ?? []))
  const extra = lines.filter((l) => !listed.has(l.name)).map((l) => byName.get(l.name)!)   // an index not in the rows
  if (extra.length) rows.splice(rows.length - 1, 0, extra)
  const adl = adlLines.value[0]
  return { rows: rows.filter((r) => r.length), adl: adl ? last(adl) : 0 }
})

// ---- The amount traded, in 亿元 ----
const amount = useStats('market.amountRange')
const yi = (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(2)}万亿` : `${v.toFixed(0)}亿`)
const amountLines = computed<Line[]>(() => [{ name: '成交额', color: '#2563eb', points: series(amount.days.value, (d) => d.amount / 1e8) }])
const amountSummary = computed(() => {
  const days = amount.days.value
  if (!days.length) return null
  const hi = days.reduce((a, d) => (d.amount > a.amount ? d : a))
  const lo = days.reduce((a, d) => (d.amount < a.amount ? d : a))
  const last = days[days.length - 1]
  const prev = days.length > 1 ? days[days.length - 2] : null
  return { n: days.length, last, avg: avg(days, (d) => d.amount), hi, lo,
           change: prev && prev.amount ? (last.amount / prev.amount - 1) * 100 : null }
})
const note = computed(() => trend.data.value?.note || amount.data.value?.note || '')
</script>

<template>
  <div class="stats">
    <!-- The day's spread of changes -->
    <section class="card wide">
      <div class="head">
        <h3>涨跌分布</h3>
        <span class="muted small">{{ date }} · 全部A股 {{ spread.total }} 只</span>
      </div>
      <p class="sum">
        <span class="up">上涨 {{ spread.up }} 家（{{ pctOf(spread.up, spread.total) }}）</span> ·
        <span class="down">下跌 {{ spread.down }} 家（{{ pctOf(spread.down, spread.total) }}）</span> ·
        <span>平盘 {{ spread.flat }} 家（{{ pctOf(spread.flat, spread.total) }}）</span>
      </p>
      <div class="bars">
        <div v-for="(b, i) in spread.bars" :key="i" class="bar" :title="`${SIDE[b.side].name} ${b.label}：${b.count} 家（${pctOf(b.count, spread.total)}）`">
          <span class="count">{{ b.count }}</span>
          <div class="track"><div class="fill" :style="{ height: `${b.h * 100}%`, background: SIDE[b.side].color }" /></div>
          <span class="label"><b :style="{ color: SIDE[b.side].color }">{{ SIDE[b.side].name }}</b>{{ b.side === 'flat' ? '' : b.label }}</span>
          <span class="muted share">{{ pctOf(b.count, spread.total) }}</span>
        </div>
      </div>
    </section>

    <LimitBoard :date="date" />
    <IndustryBoard :rows="rows" @pick="(n) => emit('industry', n)" />

    <!-- Rises and falls over time -->
    <section class="card">
      <div class="head">
        <h3>历史涨跌趋势</h3>
        <Select v-model="trend.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
      </div>
      <p v-if="trend.error.value" class="bad small">{{ trend.error.value }}</p>
      <p v-else-if="trendSummary" class="sum">
        <template v-if="trendSummary.n === 1">
          {{ trendSummary.end }}：<span class="up">上涨 {{ trendSummary.last.up }}</span> ·
          <span class="down">下跌 {{ trendSummary.last.down }}</span> · 平 {{ trendSummary.last.flat }}
        </template>
        <template v-else>
          {{ trendSummary.start }} 至 {{ trendSummary.end }} 共 {{ trendSummary.n }} 个交易日：
          <span class="up">涨多跌少 {{ trendSummary.upDays }} 天</span> ·
          <span class="down">跌多涨少 {{ trendSummary.downDays }} 天</span>；
          日均上涨 {{ trendSummary.avgUp }} 家、下跌 {{ trendSummary.avgDown }} 家、平 {{ trendSummary.avgFlat }} 家
        </template>
      </p>
      <p v-else-if="trend.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中（首次需扫描一年个股日线，约数秒）</p>
      <LineChart v-if="trend.data.value" :lines="trendLines" :format="(v) => `${Math.round(v)}`" />
    </section>

    <!-- Limit moves over time -->
    <section class="card">
      <div class="head">
        <h3>涨停跌停趋势</h3>
        <Select v-model="limits.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
      </div>
      <p v-if="limits.error.value" class="bad small">{{ limits.error.value }}</p>
      <p v-else-if="limitSummary" class="sum">
        <template v-if="limitSummary.n === 1">
          {{ limitSummary.last.date }}：<span class="up">涨停 {{ limitSummary.last.limit_up }}</span> ·
          <span class="down">跌停 {{ limitSummary.last.limit_down }}</span> · 炸板 {{ limitSummary.last.broken }} · 炸板率 {{ limitSummary.brokenRate }}%
        </template>
        <template v-else>
          {{ limitSummary.n }} 个交易日：日均 <span class="up">涨停 {{ limitSummary.avgUp }}</span> 家、
          <span class="down">跌停 {{ limitSummary.avgDown }}</span> 家，平均炸板率 {{ limitSummary.brokenRate }}%；
          涨停最多 {{ limitSummary.top.limit_up }} 家（{{ limitSummary.top.date }}），
          跌停最多 {{ limitSummary.bottom.limit_down }} 家（{{ limitSummary.bottom.date }}）
        </template>
      </p>
      <p v-else-if="limits.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
      <LineChart v-if="limits.data.value" :lines="limitLines" :format="(v) => `${Math.round(v)}`" />
    </section>

    <!-- 赚钱效应 -->
    <section class="card">
      <div class="head">
        <h3>赚钱效应</h3>
        <Select v-model="effect.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
      </div>
      <p v-if="effect.error.value" class="bad small">{{ effect.error.value }}</p>
      <p v-else-if="effectSummary" class="sum">
        <template v-if="effectSummary.n === 1">
          当日个股涨幅中位数 <b :class="effectSummary.last >= 0 ? 'up' : 'down'">{{ signed(effectSummary.last) }}</b>，
          上涨个股占 {{ effectSummary.upShare.toFixed(1) }}%
        </template>
        <template v-else>
          {{ effectSummary.n }} 个交易日中位数为正 <span class="up">{{ effectSummary.positive }} 天</span>、
          为负 <span class="down">{{ effectSummary.n - effectSummary.positive }} 天</span>；日均
          <span :class="effectSummary.mean >= 0 ? 'up' : 'down'">{{ signed(effectSummary.mean) }}</span>，
          累计 <b :class="effectSummary.total >= 0 ? 'up' : 'down'">{{ signed(effectSummary.total, 1) }}</b>；
          上涨个股平均占 {{ effectSummary.upShare.toFixed(1) }}%
        </template>
      </p>
      <p v-else-if="effect.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
      <p class="muted small">每天全部A股涨跌幅的中位数：一半个股好于它、一半差于它，比指数更能代表多数股票的表现。</p>
      <LineChart v-if="effect.data.value" :lines="effectLines" :format="(v) => signed(v)" />
    </section>

    <!-- The indexes against the median stock -->
    <section class="card">
      <div class="head">
        <h3>指数与腾落线</h3>
        <Select v-model="versus.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
      </div>
      <p v-if="versus.error.value" class="bad small">{{ versus.error.value }}</p>
      <p v-else-if="versus.data.value?.index_error" class="bad small">{{ versus.data.value.index_error }}，只显示个股统计</p>
      <div v-if="versusSummary" class="sum">
        <div class="muted small">自 {{ versus.data.value?.index_base }} 收盘以来（点击隐藏或显示折线）：</div>
        <div v-for="(row, i) in versusSummary.rows" :key="i" class="irow">
          <button v-for="it in row" :key="it.name" type="button" class="item toggle" :class="{ off: hidden.includes(it.name) }"
                  :title="hidden.includes(it.name) ? '点击显示' : '点击隐藏'" @click="toggleLine(it.name)">
            <i class="dot" :style="{ background: it.color }" />{{ it.name }}
            <b :class="it.value >= 0 ? 'up' : 'down'">{{ signed(it.value, 1) }}</b>
          </button>
        </div>
        <div class="irow">腾落线 <b :class="versusSummary.adl >= 0 ? 'up' : 'down'">{{ versusSummary.adl > 0 ? '+' : '' }}{{ versusSummary.adl }}</b></div>
      </div>
      <p v-else-if="versus.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
      <p class="muted small">指数涨而个股中位数和腾落线走弱，说明只是少数权重股在撑；反之是普涨。</p>
      <LineChart v-if="versus.data.value" :lines="shownVersusLines" :format="(v) => signed(v, 1)" :height="220" pick :rows="INDEX_ROWS" />
      <LineChart v-if="versus.data.value" :lines="adlLines" :format="(v) => `${Math.round(v)}`" :height="140" />
    </section>

    <!-- The amount traded over time -->
    <section class="card">
      <div class="head">
        <h3>市场成交额</h3>
        <Select v-model="amount.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
      </div>
      <p v-if="amount.error.value" class="bad small">{{ amount.error.value }}</p>
      <p v-else-if="amountSummary" class="sum">
        {{ amountSummary.last.date }} 成交 <b>{{ yi(amountSummary.last.amount / 1e8) }}</b>
        <span v-if="amountSummary.change !== null" :class="amountSummary.change >= 0 ? 'up' : 'down'">
          （较前一日 {{ signed(amountSummary.change, 1) }}）</span>
        <template v-if="amountSummary.n > 1">
          ；{{ amountSummary.n }} 个交易日日均 {{ yi(amountSummary.avg / 1e8) }}，
          最高 {{ yi(amountSummary.hi.amount / 1e8) }}（{{ amountSummary.hi.date }}），
          最低 {{ yi(amountSummary.lo.amount / 1e8) }}（{{ amountSummary.lo.date }}）
        </template>
      </p>
      <p v-else-if="amount.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
      <LineChart v-if="amount.data.value" :lines="amountLines" :format="yi" />
    </section>
    <p v-if="note" class="muted small foot">{{ note }}</p>
  </div>
</template>

<style scoped>
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 460px), 1fr)); gap: 12px; margin-top: 12px; }
.wide, .foot { grid-column: 1 / -1; }
.foot { margin: 0; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h3 { margin: 0; font-size: 15px; }
.sum { margin: 8px 0; font-size: 13px; line-height: 1.6; font-variant-numeric: tabular-nums; }
.small { font-size: 12px; }
.bad { color: var(--up); }
.range { width: 110px; }
.item { margin-right: 10px; white-space: nowrap; }
.irow { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 4px; }
.toggle { font: inherit; color: inherit; background: none; border: 1px solid transparent; border-radius: 6px;
          padding: 1px 6px; margin-right: 4px; cursor: pointer; }
.toggle:hover { border-color: var(--border); }
.toggle.off { opacity: 0.4; text-decoration: line-through; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 3px; }
.bars { display: grid; grid-template-columns: repeat(11, 1fr); gap: 6px; align-items: end; }
.bar { display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 0; font-variant-numeric: tabular-nums; }
.track { width: 100%; max-width: 56px; height: 160px; display: flex; align-items: flex-end; background: #f6f7f9; border-radius: 4px; }
.fill { width: 100%; min-height: 1px; border-radius: 4px 4px 0 0; }
.count { font-size: 13px; font-weight: 600; }
.label { font-size: 12px; white-space: nowrap; }
.label b { font-weight: 600; margin-right: 1px; }
.share { font-size: 11px; }
@media (max-width: 760px) {
  .bars { gap: 2px; }
  .track { height: 110px; }
  .label { font-size: 10px; }
}
</style>
