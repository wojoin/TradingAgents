<script setup lang="ts">
// 两融余额: margin financing plus securities lending on the Shanghai and Shenzhen exchanges,
// with each day's change and its pace: the 5- and 20-day slopes, and whether the recent pace is
// above the trend (leverage speeding up) or below it. A day is published the next morning.
import { computed, ref, watch } from 'vue'
import Select from 'primevue/select'
import { api, type MarketMargin } from '../api'
import { RANGES, rangeRef } from '../statsRange'
import LineChart, { type Line } from './LineChart.vue'

const props = defineProps<{ date: string | null }>()
const UP = '#e5484d'
const DOWN = '#1f9d55'

const range = rangeRef('market.marginRange')
const data = ref<MarketMargin | null>(null)
const error = ref('')
const loading = ref(false)
watch([range, () => props.date], async ([r, d]) => {
  if (!d) return
  loading.value = true
  error.value = ''
  try {
    const m = await api.marketMargin(r, d)
    if (range.value === r && props.date === d) data.value = m
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}, { immediate: true })

const yi = (v: number) => (Math.abs(v) >= 1e12 ? `${(v / 1e12).toFixed(3)}万亿` : `${(v / 1e8).toFixed(0)}亿`)
const signedYi = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${(v / 1e8).toFixed(0)}亿`)
const cls = (v: number | null | undefined) => (!v ? '' : v > 0 ? 'up' : 'down')

const days = computed(() => data.value?.days || [])
const balanceLines = computed<Line[]>(() => [
  { name: '两融余额', color: '#2563eb', points: days.value.flatMap((d) => (d.total === null ? [] : [{ time: d.date, value: d.total }])) },
])
const changeLines = computed<Line[]>(() => [{
  name: '较前日', color: UP, bars: true,
  points: days.value.flatMap((d) => (d.chg === null ? [] : [{ time: d.date, value: d.chg, color: d.chg >= 0 ? UP : DOWN }])),
}])
// The pace: how much the balance moves a day, over the last 5 and the last 20 trading days.
const FAST = '#f59e0b'
const SLOW = '#7c3aed'
const perDay = (v: number) => `${v > 0 ? '+' : ''}${(v / 1e8).toFixed(1)}亿/日`
const slopeLines = computed<Line[]>(() => [
  { name: '近5日斜率', color: FAST, points: days.value.flatMap((d) => (d.s5 === null ? [] : [{ time: d.date, value: d.s5 }])) },
  { name: '20日斜率', color: SLOW, points: days.value.flatMap((d) => (d.s20 === null ? [] : [{ time: d.date, value: d.s20 }])) },
])
const hovered = ref<string | null>(null)       // the day under the mouse on any of the three charts
const byDate = computed(() => new Map(days.value.map((d) => [d.date, d])))
// 加快 / 由减转增 read as money coming in, 去杠杆 / 放缓 / 由增转减 as going out or tiring.
const trendCls = (t: string | null | undefined) =>
  !t ? '' : /加杠杆加快|由减转增|去杠杆放缓/.test(t) ? 'up' : /走平/.test(t) ? '' : 'down'
const pctOf = (chg: number | null, total: number | null) =>
  chg === null || total === null || total === chg ? null : (chg / (total - chg)) * 100
const signedPct = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
const rates = computed(() => {
  const d = days.value[days.value.length - 1]
  if (!d) return []
  return [
    { label: '较前日', chg: d.chg, pct: pctOf(d.chg, d.total) },
    { label: '近5日', chg: d.chg5, pct: pctOf(d.chg5, d.total) },
    { label: '近20日', chg: d.chg20, pct: pctOf(d.chg20, d.total) },
  ]
})

const summary = computed(() => {
  const ds = days.value
  const last = ds[ds.length - 1]
  if (!last || last.total === null) return null
  const first = ds[0]
  const span = first && first.total !== null && ds.length > 1 ? last.total - first.total + (first.chg ?? 0) : null
  return { last, span, pct: span !== null && last.total ? (span / (last.total - span)) * 100 : null }
})
</script>

<template>
  <section class="card">
    <div class="head">
      <h3>两融余额</h3>
      <Select v-model="range" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="error" class="bad small">{{ error }}</p>
    <p v-else-if="summary" class="sum">
      {{ summary.last.date }}：沪深两融余额 <b>{{ yi(summary.last.total!) }}</b>，较前日
      <b :class="cls(summary.last.chg)">{{ signedYi(summary.last.chg) }}</b>
      <template v-if="summary.span !== null">；区间 <b :class="cls(summary.span)">{{ signedYi(summary.span) }}</b>
        <span class="muted">（{{ summary.pct! > 0 ? '+' : '' }}{{ summary.pct?.toFixed(1) }}%）</span></template>
      <span v-if="data && date && data.as_of < date" class="muted">；交易所次日公布，截至 {{ data.as_of }}</span>
    </p>
    <p v-else-if="loading" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <div v-if="summary" class="rates">
      <span v-for="r in rates" :key="r.label">{{ r.label }} <b :class="cls(r.chg)">{{ signedYi(r.chg) }}</b>
        <span v-if="r.pct !== null" class="muted">（{{ r.pct > 0 ? '+' : '' }}{{ r.pct.toFixed(2) }}%）</span></span>
      <span v-if="summary.last.s5 !== null && summary.last.s20 !== null">速率：近5日 <b :class="cls(summary.last.s5)">{{ perDay(summary.last.s5) }}</b>，
        20日 <b :class="cls(summary.last.s20)">{{ perDay(summary.last.s20) }}</b>
        → <b class="tag" :class="trendCls(summary.last.trend)">{{ summary.last.trend }}</b></span>
    </div>
    <p class="muted small sub">融资（借钱买股）加融券（借股卖出）的未还余额，反映杠杆资金的多少。余额持续增加说明加杠杆做多，单日大幅减少常是去杠杆、被动平仓，与指数同向放大波动。
      <span v-if="data?.note" class="bad">{{ data.note }}</span></p>
    <LineChart v-if="data" :lines="balanceLines" :format="yi" :height="160" :sync="hovered" @hover="hovered = $event">
      <template #legend="{ day }">
        <span v-if="day && byDate.get(day)" class="small">较前日 <b :class="cls(byDate.get(day)!.chg)">{{ signedYi(byDate.get(day)!.chg) }}</b>
          <span v-if="pctOf(byDate.get(day)!.chg, byDate.get(day)!.total) !== null" class="muted">（{{ signedPct(pctOf(byDate.get(day)!.chg, byDate.get(day)!.total)!) }}）</span></span>
      </template>
    </LineChart>
    <LineChart v-if="data" :lines="changeLines" :format="signedYi" :height="110" :sync="hovered" @hover="hovered = $event" />
    <template v-if="data && slopeLines[0].points.length">
      <p class="muted small sub">速率：余额每天平均增减多少（最小二乘斜率）。<b>橙线（近5日）在紫线（20日）之上 = 加杠杆在加快或去杠杆在放缓</b>，在其下 = 加杠杆在放缓或去杠杆在加快；穿过 0 轴是方向转变。</p>
      <LineChart :lines="slopeLines" :format="perDay" :height="150" :sync="hovered" @hover="hovered = $event" :levels="[{ value: 0, title: '' }]">
        <template #legend="{ day }">
          <b v-if="day && byDate.get(day)?.trend" class="tag" :class="trendCls(byDate.get(day)?.trend)">{{ byDate.get(day)?.trend }}</b>
        </template>
      </LineChart>
    </template>
  </section>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h3 { margin: 0; font-size: 15px; }
.sum { margin: 8px 0; font-size: 13px; line-height: 1.6; font-variant-numeric: tabular-nums; }
.small { font-size: 12px; }
.sub { margin: 6px 0; }
.bad { color: var(--up); }
.range { width: 110px; }
.rates { display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 4px 0 8px; font-size: 13px; font-variant-numeric: tabular-nums; }
.tag { padding: 0 6px; border-radius: 4px; background: var(--p-content-hover-background, #f1f5f9); }

</style>
