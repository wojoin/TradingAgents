<script lang="ts">
import { api as breadthApi, type MarketBreadth as Breadth, type StatsRange as Range } from '../api'
// One request per (span, day), shared by every card on the page.
const cache = new Map<string, Promise<Breadth>>()
function fetchBreadth(range: Range, end: string): Promise<Breadth> {
  const key = `${range}|${end}`
  if (!cache.has(key)) {
    const p = breadthApi.marketBreadth(range, end)
    p.catch(() => cache.delete(key))
    cache.set(key, p)
  }
  return cache.get(key)!
}
</script>

<script setup lang="ts">
// The market's breadth and short-term mood, as cards in the stats grid: 涨停溢价 (yesterday's
// limit-ups today), 连板晋级率, 大小盘风格, new highs and lows, and the share above the MAs.
// Each card has its own span, remembered in this browser.
import { computed, ref, watch } from 'vue'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import type { BreadthDay, MarketBreadth } from '../api'
import { RANGES, rangeRef } from '../statsRange'
import LineChart, { type Line } from './LineChart.vue'

// ``cards``: which to show (mood, prem, promo, height, size, highs, ma); all by default.
type Card = 'mood' | 'prem' | 'promo' | 'height' | 'size' | 'highs' | 'ma'
const props = defineProps<{ date: string | null; cards?: Card[] }>()
const has = (c: Card) => !props.cards || props.cards.includes(c)

const UP = '#e5484d'
const DOWN = '#1f9d55'
const BAND_COLORS: Record<string, string> = { 大盘: '#2563eb', 中盘: '#db2777', 小盘: '#0891b2', 微盘: '#f59e0b' }

function useBreadth(key: string, card: Card) {
  const range = rangeRef(key)
  const data = ref<MarketBreadth | null>(null)
  const loading = ref(false)
  const error = ref('')
  watch([range, () => props.date], async ([r, d]) => {
    if (!d || !has(card)) return
    loading.value = true
    error.value = ''
    try {
      const b = await fetchBreadth(r, d)
      if (range.value === r && props.date === d) data.value = b
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }, { immediate: true })
  const days = computed<BreadthDay[]>(() => data.value?.days || [])
  const last = computed<BreadthDay | null>(() => days.value[days.value.length - 1] ?? null)
  return { range, data, loading, error, days, last }
}

type Num = number | null | undefined
const pts = (days: BreadthDay[], f: (d: BreadthDay) => Num) =>
  days.flatMap((d) => { const v = f(d); return v === null || v === undefined ? [] : [{ time: d.date, value: v }] })
const mean = (xs: Num[]) => {
  const v = xs.filter((x): x is number => typeof x === 'number')
  return v.length ? v.reduce((a, x) => a + x, 0) / v.length : null
}
const pct = (v: Num, d = 1) => (v === null || v === undefined ? '—' : `${v.toFixed(d)}%`)
const signed = (v: Num, d = 2) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(d)}%`)
const cls = (v: Num) => (!v ? '' : v > 0 ? 'up' : 'down')

// ---- 情绪综合分: six readings on 0–100, averaged ----
const mood = useBreadth('market.moodRange', 'mood')
const MOOD_PARTS: { key: keyof BreadthDay; label: string; rule: string }[] = [
  { key: 'm_updown', label: '涨跌比', rule: '上涨 ÷（上涨 + 下跌）' },
  { key: 'm_limit', label: '涨停跌停比', rule: '涨停 ÷（涨停 + 跌停）' },
  { key: 'm_seal', label: '封板率', rule: '涨停 ÷（涨停 + 炸板）' },
  { key: 'm_prem', label: '涨停溢价', rule: '昨日涨停今日平均涨幅，−5% 为 0，+5% 为 100' },
  { key: 'm_promo', label: '晋级率', rule: '昨日涨停今日再涨停比例，40% 及以上为 100' },
  { key: 'm_height', label: '空间板', rule: '最高连板，1 板为 0，8 板及以上为 100' },
]
const moodZone = (v: Num) => (v === null || v === undefined ? { label: '—', color: '#9aa4b2' }
  : v >= 80 ? { label: '过热', color: '#b91c1c' } : v >= 60 ? { label: '活跃', color: UP }
    : v >= 40 ? { label: '中性', color: '#f59e0b' } : v >= 20 ? { label: '低迷', color: '#0891b2' } : { label: '冰点', color: DOWN })
const moodLines = computed<Line[]>(() => [{ name: '情绪综合分', color: '#7c3aed', points: pts(mood.days.value, (d) => d.mood) }])
const moodAvg = computed(() => mean(mood.days.value.map((d) => d.mood)))

// ---- 涨停溢价: yesterday's limit-ups today ----
const prem = useBreadth('market.premRange', 'prem')
const premLines = computed<Line[]>(() => [{
  name: '涨停溢价', color: UP, bars: true,
  points: prem.days.value.flatMap((d) => d.prem_avg === null ? [] : [{ time: d.date, value: d.prem_avg, color: d.prem_avg >= 0 ? UP : DOWN }]),
}])
const premSummary = computed(() => {
  const days = prem.days.value.filter((d) => d.prem_avg !== null)
  if (!days.length) return null
  return { avg: mean(days.map((d) => d.prem_avg)), pos: days.filter((d) => (d.prem_avg ?? 0) > 0).length, n: days.length }
})

// ---- 连板晋级率 ----
const promo = useBreadth('market.promoRange', 'promo')
const promoLines = computed<Line[]>(() => [
  { name: '首板→2板', color: '#f59e0b', points: pts(promo.days.value, (d) => d.promo_1) },
  { name: '连板晋级', color: UP, points: pts(promo.days.value, (d) => d.promo_multi) },
  { name: '全部涨停', color: '#6b7785', points: pts(promo.days.value, (d) => d.promo_all) },
])

// ---- 空间板: the highest run of limit-ups, and how many are on a run ----
const height = useBreadth('market.heightRange', 'height')
const heightLines = computed<Line[]>(() => [
  { name: '最高连板', color: UP, points: pts(height.days.value, (d) => d.height) },
  { name: '连板家数', color: '#f59e0b', points: pts(height.days.value, (d) => d.multi_n) },
])
const heightSummary = computed(() => {
  const ds = height.days.value.filter((d) => d.height !== null)
  if (!ds.length) return null
  const hs = ds.map((d) => d.height as number)
  const top = Math.max(...hs)
  return { top, topDay: ds[hs.lastIndexOf(top)].date, avg: mean(hs) }
})

// ---- 大小盘风格: each band's median change, compounded over the span ----
const size = useBreadth('market.sizeRange', 'size')
const bands = computed(() => size.data.value?.bands || [])
const sizeLines = computed<Line[]>(() => bands.value.map((b) => {
  let f = 1
  return {
    name: b.name, color: BAND_COLORS[b.name] || '#9aa4b2',
    points: size.days.value.flatMap((d) => {
      const v = d[`size_${b.name}`]
      if (v === null || v === undefined) return []
      f *= 1 + v / 100
      return [{ time: d.date, value: (f - 1) * 100 }]
    }),
  }
}))
const sizeSummary = computed(() => bands.value.map((b, i) => ({
  ...b, color: BAND_COLORS[b.name], today: size.last.value?.[`size_${b.name}`] ?? null,
  total: sizeLines.value[i]?.points.at(-1)?.value ?? null,
})))

// ---- 新高新低 ----
const highs = useBreadth('market.highRange', 'highs')
const HIGH_SPANS = [{ value: 60, label: '60日' }, { value: 250, label: '250日（52周）' }]
const highSpan = ref<60 | 250>(60)
const highLines = computed<Line[]>(() => {
  const n = highSpan.value
  return [
    { name: `${n}日新高`, color: UP, points: pts(highs.days.value, (d) => (n === 60 ? d.nh60 : d.nh250)) },
    { name: `${n}日新低`, color: DOWN, points: pts(highs.days.value, (d) => (n === 60 ? d.nl60 : d.nl250)) },
  ]
})
const highLast = computed(() => {
  const d = highs.last.value
  if (!d) return null
  return highSpan.value === 60 ? { hi: d.nh60, lo: d.nl60 } : { hi: d.nh250, lo: d.nl250 }
})

// ---- 均线上方占比 ----
const mas = useBreadth('market.maRange', 'ma')
const maLines = computed<Line[]>(() => [
  { name: '站上20日线', color: '#f59e0b', points: pts(mas.days.value, (d) => d.ma20) },
  { name: '站上60日线', color: '#2563eb', points: pts(mas.days.value, (d) => d.ma60) },
])
const maMood = (v: Num) => (v === null || v === undefined ? '' : v >= 80 ? '偏热' : v <= 20 ? '超跌' : '')
</script>

<template>
  <!-- 情绪综合分 -->
  <section v-if="has('mood')" class="card wide">
    <div class="head">
      <h3>情绪综合分</h3>
      <Select v-model="mood.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="mood.error.value" class="bad small">{{ mood.error.value }}</p>
    <p v-else-if="mood.loading.value && !mood.last.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <div v-if="mood.last.value" class="mood">
      <div class="score">
        <div class="muted small">{{ mood.last.value.date }}</div>
        <div class="big" :style="{ color: moodZone(mood.last.value.mood).color }">{{ mood.last.value.mood?.toFixed(0) ?? '—' }}</div>
        <div class="zone" :style="{ background: moodZone(mood.last.value.mood).color }">{{ moodZone(mood.last.value.mood).label }}</div>
        <div v-if="moodAvg !== null && mood.days.value.length > 1" class="muted small">区间平均 {{ moodAvg.toFixed(0) }}</div>
      </div>
      <div class="parts">
        <div v-for="p in MOOD_PARTS" :key="p.key" class="part" :title="p.rule">
          <span class="plabel">{{ p.label }}</span>
          <span class="ptrack"><span class="pfill" :style="{ width: `${(mood.last.value[p.key] as number | null) ?? 0}%`, background: moodZone(mood.last.value[p.key] as number | null).color }" /></span>
          <span class="pval">{{ (mood.last.value[p.key] as number | null)?.toFixed(0) ?? '—' }}</span>
        </div>
      </div>
      <div class="mchart">
        <LineChart :lines="moodLines" :format="(v) => v.toFixed(0)" :height="170" />
      </div>
    </div>
    <p class="muted small sub">把涨跌比、涨停跌停比、封板率、涨停溢价、晋级率、空间板六项各折算成 0–100 后取平均（鼠标停在各项上看折算方法）。
      ≥80 过热、60–80 活跃、40–60 中性、20–40 低迷、&lt;20 冰点。过热时追高风险大，冰点后回升常是短线机会；权重为等权，仅作参考。</p>
  </section>

  <!-- 涨停溢价 -->
  <section v-if="has('prem')" class="card">
    <div class="head">
      <h3>涨停溢价</h3>
      <Select v-model="prem.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="prem.error.value" class="bad small">{{ prem.error.value }}</p>
    <p v-else-if="prem.last.value" class="sum">
      {{ prem.last.value.date }}：昨日涨停 {{ prem.last.value.prem_n ?? '—' }} 只，今日平均
      <b :class="cls(prem.last.value.prem_avg)">{{ signed(prem.last.value.prem_avg) }}</b>，上涨占比 {{ pct(prem.last.value.prem_up, 0) }}
      <template v-if="premSummary && premSummary.n > 1">；区间平均 <b :class="cls(premSummary.avg)">{{ signed(premSummary.avg) }}</b>，
        {{ premSummary.pos }}/{{ premSummary.n }} 天为正</template>
    </p>
    <p v-else-if="prem.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small">昨日收盘涨停的股票今天的平均涨跌幅。为正说明追涨停能赚钱、短线情绪好；持续为负说明打板亏钱，情绪退潮。</p>
    <LineChart v-if="prem.data.value" :lines="premLines" :format="(v) => signed(v)" :height="180" />
  </section>

  <!-- 连板晋级率 -->
  <section v-if="has('promo')" class="card">
    <div class="head">
      <h3>连板晋级率</h3>
      <Select v-model="promo.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="promo.error.value" class="bad small">{{ promo.error.value }}</p>
    <p v-else-if="promo.last.value" class="sum">
      {{ promo.last.value.date }}：首板→2板 <b>{{ pct(promo.last.value.promo_1) }}</b> ·
      2板→3板 <b>{{ pct(promo.last.value.promo_2) }}</b> · 3板以上再晋级 <b>{{ pct(promo.last.value.promo_3) }}</b> ·
      连板整体 <b>{{ pct(promo.last.value.promo_multi) }}</b>
    </p>
    <p v-else-if="promo.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small">昨日涨停的股票今天再次涨停的比例。晋级率高说明接力资金积极、连板容易走出来；高位晋级率骤降常是情绪见顶的信号。</p>
    <LineChart v-if="promo.data.value" :lines="promoLines" :format="(v) => pct(v)" :height="180" />
  </section>

  <!-- 空间板高度 -->
  <section v-if="has('height')" class="card">
    <div class="head">
      <h3>空间板高度</h3>
      <Select v-model="height.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="height.error.value" class="bad small">{{ height.error.value }}</p>
    <p v-else-if="height.last.value" class="sum">
      {{ height.last.value.date }}：最高 <b class="up">{{ height.last.value.height ?? '—' }} 连板</b>，连板（2板及以上）{{ height.last.value.multi_n ?? '—' }} 只
      <template v-if="heightSummary && height.days.value.length > 1">；区间最高 {{ heightSummary.top }} 板（{{ heightSummary.topDay }}），平均 {{ heightSummary.avg?.toFixed(1) }} 板</template>
    </p>
    <p v-else-if="height.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small">每天涨停股中连续涨停天数最多的（空间板）和连板家数。高度不断抬升是情绪发酵期，高度骤降、龙头断板是退潮期，低位反复是冰点。</p>
    <LineChart v-if="height.data.value" :lines="heightLines" :format="(v) => `${Math.round(v)}`" :height="180" />
  </section>

  <!-- 大小盘风格 -->
  <section v-if="has('size')" class="card">
    <div class="head">
      <h3>大小盘风格</h3>
      <Select v-model="size.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="size.error.value" class="bad small">{{ size.error.value }}</p>
    <div v-else-if="size.last.value" class="sum">
      <div class="muted small">{{ size.last.value.date }} 中位涨幅 · 区间累计</div>
      <div class="bands">
        <span v-for="b in sizeSummary" :key="b.name" class="item" :title="b.rule">
          <i class="dot" :style="{ background: b.color }" />{{ b.name }}
          <b :class="cls(b.today)">{{ signed(b.today) }}</b> · <span :class="cls(b.total)">{{ signed(b.total, 1) }}</span>
        </span>
      </div>
    </div>
    <p v-else-if="size.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small">按流通市值每天排名分档（大盘前 300、中盘 301–800、小盘 801–1800、微盘最小 400，不含 ST），看各档股票涨幅的中位数。哪条线在上，资金就偏好哪类股票。</p>
    <LineChart v-if="size.data.value" :lines="sizeLines" :format="(v) => signed(v, 1)" :height="200" pick />
  </section>

  <!-- 新高新低 -->
  <section v-if="has('highs')" class="card">
    <div class="head">
      <h3>新高新低</h3>
      <Select v-model="highs.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <SelectButton v-model="highSpan" :options="HIGH_SPANS" option-label="label" option-value="value" :allow-empty="false" size="small" class="spans" />
    <p v-if="highs.error.value" class="bad small">{{ highs.error.value }}</p>
    <p v-else-if="highLast" class="sum">
      {{ highs.last.value?.date }}：创{{ highSpan }}日新高 <b class="up">{{ highLast.hi ?? '—' }}</b> 家，新低 <b class="down">{{ highLast.lo ?? '—' }}</b> 家
    </p>
    <p v-else-if="highs.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small">收盘价（复权）高于此前 {{ highSpan }} 个交易日每天收盘的为新高，低于的为新低。新高多于新低说明市场在走强；指数创新高而新高家数减少，是上涨面收窄的警示。</p>
    <LineChart v-if="highs.data.value" :lines="highLines" :format="(v) => `${Math.round(v)}`" :height="180" />
  </section>

  <!-- 均线上方占比 -->
  <section v-if="has('ma')" class="card">
    <div class="head">
      <h3>均线上方占比</h3>
      <Select v-model="mas.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="mas.error.value" class="bad small">{{ mas.error.value }}</p>
    <p v-else-if="mas.last.value" class="sum">
      {{ mas.last.value.date }}：站上20日线 <b>{{ pct(mas.last.value.ma20) }}</b>
      <span v-if="maMood(mas.last.value.ma20)" class="muted">（{{ maMood(mas.last.value.ma20) }}）</span> ·
      站上60日线 <b>{{ pct(mas.last.value.ma60) }}</b>
      <span v-if="maMood(mas.last.value.ma60)" class="muted">（{{ maMood(mas.last.value.ma60) }}）</span>
    </p>
    <p v-else-if="mas.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small">收盘价（复权）高于自身 20 日、60 日均线的股票占比。高于 80% 偏热、低于 20% 超跌；20 日线反映短期，60 日线反映中期。</p>
    <LineChart v-if="mas.data.value" :lines="maLines" :format="(v) => pct(v)" :height="180" />
  </section>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h3 { margin: 0; font-size: 15px; }
.sum { margin: 8px 0; font-size: 13px; line-height: 1.6; font-variant-numeric: tabular-nums; }
.small { font-size: 12px; }
.bad { color: var(--up); }
.range { width: 110px; }
.spans { margin-top: 8px; }
.bands { display: flex; flex-wrap: wrap; gap: 2px 14px; }
.item { white-space: nowrap; cursor: help; }
.mood { display: grid; grid-template-columns: 120px minmax(220px, 1fr) minmax(280px, 1.4fr); gap: 20px; align-items: center; margin-top: 6px; }
.score { text-align: center; }
.big { font-size: 44px; font-weight: 700; line-height: 1.1; font-variant-numeric: tabular-nums; }
.zone { display: inline-block; color: #fff; font-size: 12px; padding: 1px 10px; border-radius: 10px; margin: 2px 0 4px; }
.parts { display: flex; flex-direction: column; gap: 6px; }
.part { display: grid; grid-template-columns: 72px 1fr 30px; gap: 8px; align-items: center; font-size: 12px; cursor: help; }
.ptrack { height: 8px; background: #f1f3f6; border-radius: 4px; overflow: hidden; }
.pfill { display: block; height: 100%; border-radius: 4px; }
.pval { text-align: right; font-variant-numeric: tabular-nums; }
.wide { grid-column: 1 / -1; }
@media (max-width: 900px) { .mood { grid-template-columns: 1fr; } }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 3px; }
</style>
