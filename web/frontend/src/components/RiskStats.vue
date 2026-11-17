<script setup lang="ts">
// 资金与风险 cards: the whole market's main-force flow (Eastmoney, the last 120 trading days),
// QVIX (the 50ETF volatility index, China's VIX) and the shares coming off lock-up in the next
// 30 days. ``cards`` picks which to show (flow, qvix, releases); all by default.
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Select from 'primevue/select'
import { api, formatYuan, type MarketFlow, type MarketQvix, type MarketReleases } from '../api'
import { RANGES, rangeRef } from '../statsRange'
import LineChart, { type Line } from './LineChart.vue'

type Card = 'flow' | 'qvix' | 'releases'
const props = defineProps<{ date: string | null; cards?: Card[] }>()
const has = (c: Card) => !props.cards || props.cards.includes(c)
const router = useRouter()

const UP = '#e5484d'
const DOWN = '#1f9d55'
type Num = number | null | undefined
const cls = (v: Num) => (!v ? '' : v > 0 ? 'up' : 'down')
const yi = (v: Num) => (v === null || v === undefined ? '—' : formatYuan(v, true))

// Loads ``get(range, day)`` whenever the span or the day changes, keeping the latest answer.
function useLoad<T>(key: string | null, card: Card, get: (r: string, d: string) => Promise<T>) {
  const range = key ? rangeRef(key) : ref('1y')
  const data = ref<T | null>(null) as { value: T | null }
  const error = ref('')
  const loading = ref(false)
  watch([range, () => props.date], async ([r, d]) => {
    if (!d || !has(card)) return
    loading.value = true
    error.value = ''
    try {
      const x = await get(r as string, d)
      if (range.value === r && props.date === d) data.value = x
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }, { immediate: true })
  return { range, data, error, loading }
}

// ---- 市场资金流 ----
const flow = useLoad<MarketFlow>('market.flowRange', 'flow', (r, d) => api.marketFlow(r as never, d))
const flowLines = computed<Line[]>(() => [{
  name: '主力净流入', color: UP, bars: true,
  points: (flow.data.value?.days || []).flatMap((d) => (d.main === null ? [] : [{ time: d.date, value: d.main, color: d.main >= 0 ? UP : DOWN }])),
}])
const flowSummary = computed(() => {
  const ds = flow.data.value?.days || []
  const last = ds[ds.length - 1]
  if (!last) return null
  const sum = ds.reduce((a, d) => a + (d.main || 0), 0)
  return { last, sum, pos: ds.filter((d) => (d.main || 0) > 0).length, n: ds.length }
})

// ---- 市场波动率 QVIX ----
const qv = useLoad<MarketQvix>('market.qvixRange', 'qvix', (r, d) => api.marketQvix(r as never, d))
const qvLines = computed<Line[]>(() => {
  const ds = qv.data.value?.days || []
  const pts = ds.flatMap((d) => (d.close === null ? [] : [{ time: d.date, value: d.close }]))
  const med = qv.data.value?.median
  return [
    { name: 'QVIX', color: '#7c3aed', points: pts },
    ...(med ? [{ name: `${qv.data.value?.since.slice(0, 4)}年以来中位数`, color: '#9aa4b2', points: pts.map((p) => ({ time: p.time, value: med })) }] : []),
  ]
})
const qvMood = computed(() => {
  const r = qv.data.value?.rank
  if (r === null || r === undefined) return ''
  return r >= 90 ? '极度恐慌' : r >= 70 ? '偏恐慌' : r <= 10 ? '极度平静（警惕自满）' : r <= 30 ? '偏平静' : '正常'
})
const qvLast = computed(() => { const ds = qv.data.value?.days || []; return ds[ds.length - 1] ?? null })

// ---- 限售解禁 ----
const rel = useLoad<MarketReleases>(null, 'releases', (_r, d) => api.marketReleases(d))
const relLines = computed<Line[]>(() => [{
  name: '解禁市值', color: '#f59e0b', bars: true,
  points: (rel.data.value?.days || []).flatMap((d) => (d.value === null ? [] : [{ time: d.date, value: d.value }])),
}])
const relShow = ref(10)
</script>

<template>
  <!-- 市场资金流 -->
  <section v-if="has('flow')" class="card">
    <div class="head">
      <h3>市场资金流</h3>
      <Select v-model="flow.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="flow.error.value" class="bad small">{{ flow.error.value }}</p>
    <div v-else-if="flowSummary" class="sum">
      {{ flowSummary.last.date }}：主力净流入 <b :class="cls(flowSummary.last.main)">{{ yi(flowSummary.last.main) }}</b>
      <span class="muted">（占成交 {{ flowSummary.last.main_pct?.toFixed(2) }}%）</span>
      <div class="split">
        超大单 <b :class="cls(flowSummary.last.super)">{{ yi(flowSummary.last.super) }}</b> ·
        大单 <b :class="cls(flowSummary.last.large)">{{ yi(flowSummary.last.large) }}</b> ·
        中单 <b :class="cls(flowSummary.last.mid)">{{ yi(flowSummary.last.mid) }}</b> ·
        小单 <b :class="cls(flowSummary.last.small)">{{ yi(flowSummary.last.small) }}</b>
      </div>
      <div v-if="flowSummary.n > 1">区间合计 <b :class="cls(flowSummary.sum)">{{ yi(flowSummary.sum) }}</b>，{{ flowSummary.pos }}/{{ flowSummary.n }} 天净流入</div>
    </div>
    <p v-else-if="flow.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small sub">东方财富全市场主力（超大单 + 大单）净流入，按成交单大小推算；只有最近约 120 个交易日。
      主力持续净流出而小单净流入，常是机构派发、散户接盘；主力由流出转为流入是资金回流的信号。</p>
    <LineChart v-if="flow.data.value" :lines="flowLines" :format="(v) => yi(v)" :height="170" />
  </section>

  <!-- 市场波动率 -->
  <section v-if="has('qvix')" class="card">
    <div class="head">
      <h3>市场波动率（QVIX）</h3>
      <Select v-model="qv.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="qv.error.value" class="bad small">{{ qv.error.value }}</p>
    <p v-else-if="qvLast && qv.data.value" class="sum">
      {{ qvLast.date }}：QVIX <b>{{ qvLast.close?.toFixed(2) }}</b>，处于 {{ qv.data.value.since.slice(0, 4) }} 年以来
      <b>{{ qv.data.value.rank?.toFixed(0) }}%</b> 分位，{{ qvMood }}
      <span class="muted">（中位数 {{ qv.data.value.median?.toFixed(2) }}）</span>
    </p>
    <p v-else-if="qv.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small sub">50ETF 期权隐含波动率，即中国版「恐慌指数」VIX。急升说明市场恐慌、避险需求大，常出现在急跌的末段；
      长期处于极低位说明市场过度平静，要警惕突然的波动。数据一般滞后一个交易日。</p>
    <LineChart v-if="qv.data.value" :lines="qvLines" :format="(v) => v.toFixed(2)" :height="170" />
  </section>

  <!-- 限售解禁 -->
  <section v-if="has('releases')" class="card">
    <div class="head">
      <h3>限售解禁</h3>
      <span class="muted small">{{ rel.data.value ? `${rel.data.value.date} 至 ${rel.data.value.end}` : '' }}</span>
    </div>
    <p v-if="rel.error.value" class="bad small">{{ rel.error.value }}</p>
    <p v-else-if="rel.data.value" class="sum">
      未来 30 天解禁 <b>{{ rel.data.value.count }}</b> 只，实际解禁市值 <b>{{ formatYuan(rel.data.value.total) }}</b>
    </p>
    <p v-else-if="rel.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small sub">限售股到期可以卖出，带来潜在抛压（东方财富）。看解禁市值大、占流通市值比例高的个股，解禁前后往往承压；
      全市场解禁集中的日子，市场整体也容易受影响。实际是否减持还要看股东意愿。</p>
    <LineChart v-if="rel.data.value && rel.data.value.days.length" :lines="relLines" :format="(v) => formatYuan(v)" :height="130" />
    <table v-if="rel.data.value?.stocks.length" class="rel">
      <thead><tr><th>股票</th><th>解禁日</th><th class="nr">解禁市值</th><th class="nr">占流通市值</th><th>类型</th></tr></thead>
      <tbody>
        <tr v-for="s in rel.data.value.stocks.slice(0, relShow)" :key="`${s.code}-${s.date}`">
          <td><a class="link" @click="router.push(`/stock/${s.code}`)">{{ s.name }}</a> <span class="muted code">{{ s.code }}</span></td>
          <td>{{ s.date.slice(5) }}</td>
          <td class="nr">{{ formatYuan(s.value) }}</td>
          <td class="nr" :class="{ heavy: (s.float_share ?? 0) >= 10 }">{{ s.float_share === null ? '—' : `${s.float_share.toFixed(1)}%` }}</td>
          <td class="muted kind">{{ s.kind }}</td>
        </tr>
      </tbody>
    </table>
    <button v-if="rel.data.value && rel.data.value.stocks.length > relShow" type="button" class="more" @click="relShow = 30">显示前 30 只</button>
  </section>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h3 { margin: 0; font-size: 15px; }
.sum { margin: 8px 0; font-size: 13px; line-height: 1.7; font-variant-numeric: tabular-nums; }
.split { font-size: 12px; }
.small { font-size: 12px; }
.sub { margin: 6px 0; }
.bad { color: var(--up); }
.range { width: 110px; }
.link { cursor: pointer; }
.link:hover { color: var(--up); }
.rel { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 8px; font-variant-numeric: tabular-nums; }
.rel th { text-align: left; font-weight: 500; color: var(--muted); padding: 3px 4px; border-bottom: 1px solid var(--border); white-space: nowrap; }
.rel td { padding: 3px 4px; border-bottom: 1px solid #f1f3f6; white-space: nowrap; }
.rel .nr { text-align: right; }
.code { font-size: 11px; }
.kind { max-width: 120px; overflow: hidden; text-overflow: ellipsis; }
.heavy { color: var(--up); font-weight: 600; }
.more { margin-top: 6px; font: inherit; font-size: 12px; background: none; border: 1px dashed var(--border); border-radius: 6px;
        padding: 2px 10px; color: var(--muted); cursor: pointer; }
</style>
