<script setup lang="ts">
// 两融余额: margin financing plus securities lending on the Shanghai and Shenzhen exchanges,
// with each day's change. A day is published the next morning, so the latest is usually yesterday.
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
    <p class="muted small sub">融资（借钱买股）加融券（借股卖出）的未还余额，反映杠杆资金的多少。余额持续增加说明加杠杆做多，单日大幅减少常是去杠杆、被动平仓，与指数同向放大波动。
      <span v-if="data?.note" class="bad">{{ data.note }}</span></p>
    <LineChart v-if="data" :lines="balanceLines" :format="yi" :height="160" />
    <LineChart v-if="data" :lines="changeLines" :format="signedYi" :height="110" />
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
</style>
