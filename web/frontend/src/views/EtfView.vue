<script setup lang="ts">
// 宽基ETF: the shares of the 19 broad-based ETFs the "national team" holds (web/server/etf_flow.py).
// Volume can be made by trading with oneself; shares move only when units are created or redeemed,
// so their change is where the big money shows. Three charts over the same days: the raw daily change
// of the 19 together, the 加仓指数 (total shares ÷ the base day's × 100) and its 5 / 20-day rate.
import { computed, ref, watch } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import SelectButton from 'primevue/selectbutton'
import { api, type EtfBroad, type EtfRange } from '../api'
import LineChart, { type Line } from '../components/LineChart.vue'

const UP = '#e5484d'
const DOWN = '#1f9d55'
const RANGES: { label: string; value: EtfRange }[] = [
  { label: '半年', value: '6m' }, { label: '一年', value: '1y' }, { label: '全部', value: 'all' },
]
const DEFAULT_BASE = '2025-11-20'
// The 加仓指数's bands: above UPPER the bottom is near; below LOWER it is time to cut positions.
const UPPER = 70
const LOWER = 30
const LEVELS = [
  { value: 100, title: '基期 100' },
  { value: UPPER, title: `上轨 ${UPPER} 接近底部`, color: UP },
  { value: LOWER, title: `下轨 ${LOWER} 需减仓`, color: DOWN },
]

function stored(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) || fallback
  } catch {
    return fallback
  }
}
function remember(key: string, v: string) {
  try {
    localStorage.setItem(key, v)
  } catch {
    /* storage unavailable: the choice lasts for this page only */
  }
}

const range = ref<EtfRange>(stored('etf.range', '1y') as EtfRange)
// v2: the default moved from 2025-12-31 to 2025-11-20 (the reference charts' base), so an old choice is dropped.
const BASE_KEY = 'etf.base.v2'
const base = ref(stored(BASE_KEY, DEFAULT_BASE))
const data = ref<EtfBroad | null>(null)
const error = ref('')
const loading = ref(false)

async function load() {
  const r = range.value
  const b = base.value
  loading.value = true
  error.value = ''
  try {
    const d = await api.etfBroad(r, b || undefined)
    if (range.value === r && base.value === b) data.value = d
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}
watch([range, base], ([r, b]) => {
  remember('etf.range', r)
  remember(BASE_KEY, b)
  load()
}, { immediate: true })

const days = computed(() => data.value?.days || [])
const byDate = computed(() => new Map(days.value.map((d) => [d.date, d])))
const names = computed(() => new Map((data.value?.funds || []).map((f) => [f.code, f.name])))

const changeLines = computed<Line[]>(() => [{
  name: '份额变化', color: UP, bars: true,
  points: days.value.flatMap((d) => (d.change === null ? [] : [{ time: d.date, value: d.change, color: d.change >= 0 ? UP : DOWN }])),
}])
const indexLines = computed<Line[]>(() => [
  { name: '加仓指数', color: '#2563eb', points: days.value.map((d) => ({ time: d.date, value: d.index })) },
])
const rateLines = computed<Line[]>(() => [
  { name: '5日速率', color: '#f59e0b', points: days.value.flatMap((d) => (d.rate5 === null ? [] : [{ time: d.date, value: d.rate5 }])) },
  { name: '20日速率', color: '#7c3aed', points: days.value.flatMap((d) => (d.rate20 === null ? [] : [{ time: d.date, value: d.rate20 }])) },
])

const hovered = ref<string | null>(null)
const shown = computed(() => {
  const ds = days.value
  return ds.find((d) => d.date === hovered.value) ?? ds[ds.length - 1] ?? null
})
const last = computed(() => days.value[days.value.length - 1] ?? null)
const low = computed(() => days.value.reduce<typeof days.value[number] | null>((m, d) => (!m || d.index < m.index ? d : m), null))

const zone = computed(() => {
  const v = last.value?.index
  if (v === undefined) return null
  if (v >= UPPER) return { text: `指数在上轨 ${UPPER} 之上，相对接近底部。`, cls: 'up' }
  if (v <= LOWER) return { text: `指数在下轨 ${LOWER} 之下，需要减仓。`, cls: 'down' }
  return { text: `指数在 ${LOWER}–${UPPER} 之间。`, cls: '' }
})
const topWeight = computed(() => (data.value?.funds || []).reduce<EtfBroad['funds'][number] | null>((m, f) => (!m || f.weight > m.weight ? f : m), null))
const signed = (v: number | null | undefined, nd = 2) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(nd)}`)
const yi = (v: number) => `${signed(v)}亿份`
const pts = (v: number) => v.toFixed(2)
const cls = (v: number | null | undefined) => (!v ? '' : v > 0 ? 'up' : 'down')
</script>

<template>
  <div class="page etf">
    <section class="card head">
      <div>
        <h2>宽基ETF</h2>
        <p class="muted small">
          19 只主要宽基 ETF（国家队重仓）的份额。成交量可以左手倒右手地对敲出来，看不出是真买还是假买；份额只在申购、赎回时变化，
          才是大资金进出的痕迹。单日份额变化噪声大，把 19 只的份额按基期份额加权、合成「加仓指数」，再看它的变化速率，趋势才清楚（算法见下方「加仓指数怎么算」）。
        </p>
      </div>
      <div class="controls">
        <label class="small muted">基期
          <input v-model.lazy="base" type="date" class="date" :max="data?.as_of" />
        </label>
        <SelectButton v-model="range" :options="RANGES" option-label="label" option-value="value" :allow-empty="false" size="small" />
      </div>
    </section>

    <p v-if="error" class="card bad">{{ error }}</p>
    <p v-else-if="loading && !data" class="card muted"><i class="pi pi-spin pi-spinner" /> 正在从上交所、深交所下载份额（首次约一分钟）</p>

    <template v-if="data">
      <section class="card sum">
        <div>
          截至 <b>{{ data.as_of }}</b>：{{ data.funds.length }} 只合计 <b>{{ last?.total.toFixed(2) }}</b> 亿份，较前日
          <b :class="cls(last?.change)">{{ signed(last?.change) }}</b> 亿份；加仓指数 <b>{{ last?.index.toFixed(2) }}</b>
          （基期 {{ data.base }} = 100，较前日 <b :class="cls(last?.index_change)">{{ signed(last?.index_change) }}</b>），5 日 <b :class="cls(last?.rate5)">{{ signed(last?.rate5) }}</b>、
          20 日 <b :class="cls(last?.rate20)">{{ signed(last?.rate20) }}</b>。
          <b v-if="zone" :class="zone.cls">{{ zone.text }}</b>
          <span v-if="low" class="muted">区间最低 {{ low.index.toFixed(2) }}（{{ low.date }}）。</span>
        </div>
        <div v-if="data.note || data.source === 'stale'" class="bad small">{{ data.note }}</div>
        <div v-if="loading" class="muted small"><i class="pi pi-spin pi-spinner" /> 更新中</div>
      </section>

      <section class="card">
        <h3>每日份额变化 <span class="muted small">{{ data.funds.length }} 只合计，亿份（原始数据，噪声大）</span></h3>
        <LineChart :lines="changeLines" :format="yi" :height="200" @hover="hovered = $event" />
        <p v-if="shown?.top.length" class="small movers">
          <span class="muted">{{ shown.date }} 变化最大：</span>
          <span v-for="[code, v] in shown.top" :key="code">{{ names.get(code) || code }}
            <b :class="cls(v)">{{ signed(v) }}</b></span>
        </p>
      </section>

      <section class="card">
        <h3>加仓指数 <span class="muted small">合计份额 ÷ 基期合计 × 100。上轨 {{ UPPER }}：升到它之上，底部区间快出来了，相对接近底部；
          下轨 {{ LOWER }}：跌到它之下，需要减仓了</span></h3>
        <LineChart :lines="indexLines" :format="pts" :height="260" :levels="LEVELS">
          <template #tooltip="{ day }">
            <div><b>{{ day }}</b></div>
            <div>加仓指数 <b class="index">{{ byDate.get(day)?.index.toFixed(2) }}</b></div>
            <div>较前日 <b :class="cls(byDate.get(day)?.index_change)">{{ signed(byDate.get(day)?.index_change) }}</b></div>
          </template>
          <template #legend="{ day }">
            <span>较前日 <b :class="cls(byDate.get(day)?.index_change)">{{ signed(byDate.get(day)?.index_change) }}</b></span>
          </template>
        </LineChart>
      </section>

      <section class="card">
        <h3>变化速率 <span class="muted small">加仓指数 5 日、20 日的变化（点）：上穿 0 是由减转加，越陡加得越快</span></h3>
        <LineChart :lines="rateLines" :format="(v: number) => signed(v)" :height="180" :levels="[{ value: 0, title: '0' }]" />
      </section>

      <section class="card algo">
        <h3>加仓指数怎么算</h3>
        <p class="small muted">记号：S<sub>i</sub>(t) 是第 i 只 ETF 在交易日 t 的基金份额（亿份，上交所、深交所每日公布的日终份额）；
          t<sub>0</sub> 是基期（默认 {{ DEFAULT_BASE }}，可在右上角修改）；N = {{ data.funds.length }}，求和 Σ 都是对这 N 只 ETF。</p>
        <ol>
          <li><b>每日份额变化（原始数据）</b>
            <div class="f">ΔS(t) = Σ<sub>i</sub> [ S<sub>i</sub>(t) − S<sub>i</sub>(t−1) ]</div>
            <p>当天 {{ data.funds.length }} 只 ETF 净申购（正）或净赎回（负）了多少亿份，即第一张图。单日噪声大，看不出趋势。</p></li>
          <li><b>加仓指数</b>
            <div class="f">I(t) = 100 × Σ<sub>i</sub> S<sub>i</sub>(t) ÷ Σ<sub>i</sub> S<sub>i</sub>(t<sub>0</sub>)</div>
            <p>当天的合计份额是基期合计份额的百分之几。基期为 100；低于 100 说明基期以来净赎回，越低赎回越多。</p></li>
          <li><b>「加权」的含义</b>：上式可以等价地写成
            <div class="f">I(t) = Σ<sub>i</sub> w<sub>i</sub> × [ 100 × S<sub>i</sub>(t) ÷ S<sub>i</sub>(t<sub>0</sub>) ]，
              w<sub>i</sub> = S<sub>i</sub>(t<sub>0</sub>) ÷ Σ<sub>j</sub> S<sub>j</sub>(t<sub>0</sub>)</div>
            <p>即每只 ETF 先算出自己的份额指数（基期 = 100），再按它在基期的份额占全部的比例 w<sub>i</sub> 加权平均，权重合计 100%。
              份额大的影响大：如 {{ topWeight?.name }} 权重 {{ topWeight?.weight.toFixed(1) }}%，它的份额变 10%，指数约变
              {{ topWeight ? (topWeight.weight / 10).toFixed(1) : '' }} 点；份额小的几乎不影响。各只的权重见下表「权重%」。
              按<b>份额</b>而不按<b>规模</b>（份额 × 净值）加权：规模随行情涨跌变化，份额只随申购、赎回变化，指数因此只反映资金进出，不受价格涨跌干扰。</p></li>
          <li><b>较前日</b>
            <div class="f">ΔI(t) = I(t) − I(t−1) = 100 × ΔS(t) ÷ Σ<sub>i</sub> S<sub>i</sub>(t<sub>0</sub>)</div>
            <p>当天的原始份额变化除以基期合计。所以加仓指数就是把每天的原始变化逐日累加起来：
              I(t) = 100 + Σ<sub>τ = t<sub>0</sub>+1 … t</sub> ΔI(τ)，噪声在累加中相互抵消，持续的申购或赎回才会留下趋势。</p></li>
          <li><b>变化速率</b>
            <div class="f">R<sub>5</sub>(t) = I(t) − I(t−5)，R<sub>20</sub>(t) = I(t) − I(t−20)（交易日）</div>
            <p>最近 5 日、20 日指数变了多少点：大于 0 在加仓，小于 0 在减仓；数值越大加得越快，由负转正是由减转加。</p></li>
          <li><b>上下轨</b>：I ≥ {{ UPPER }} 表示底部区间快出来了、相对接近底部；I ≤ {{ LOWER }} 表示需要减仓了。
            上下轨按基期 {{ DEFAULT_BASE }} 设定，换基期后指数整体按比例缩放，轨道的含义会随之变化。</li>
        </ol>
        <p v-if="last" class="example small">
          <b>以 {{ data.as_of }} 为例</b>（基期 {{ data.base }}）：基期合计 Σ S<sub>i</sub>(t<sub>0</sub>) = {{ data.base_total.toFixed(2) }} 亿份，
          当天合计 {{ last.total.toFixed(2) }} 亿份，I = 100 × {{ last.total.toFixed(2) }} ÷ {{ data.base_total.toFixed(2) }} =
          <b>{{ last.index.toFixed(2) }}</b>；当天份额变化 {{ signed(last.change) }} 亿份，较前日 = 100 × {{ signed(last.change) }} ÷
          {{ data.base_total.toFixed(2) }} = <b>{{ signed(last.index_change) }}</b>。
        </p>
      </section>

      <section class="card">
        <h3>{{ data.funds.length }} 只成分 <span class="muted small">较基期 {{ data.base }}；权重是基期份额占合计的比例，即它在加仓指数里的分量</span></h3>
        <DataTable :value="data.funds" size="small" sort-field="weight" :sort-order="-1" class="num">
          <Column field="code" header="代码" sortable />
          <Column field="name" header="名称" sortable />
          <Column field="exchange" header="市场" sortable>
            <template #body="{ data: f }">{{ f.exchange === 'SH' ? '沪' : '深' }}</template>
          </Column>
          <Column field="shares" header="份额(亿份)" sortable>
            <template #body="{ data: f }">{{ f.shares.toFixed(2) }}</template>
          </Column>
          <Column field="day" header="当日变化" sortable>
            <template #body="{ data: f }"><span :class="cls(f.day)">{{ signed(f.day) }}</span></template>
          </Column>
          <Column field="since_base" header="较基期(亿份)" sortable>
            <template #body="{ data: f }"><span :class="cls(f.since_base)">{{ signed(f.since_base) }}</span></template>
          </Column>
          <Column field="since_base_pct" header="较基期%" sortable>
            <template #body="{ data: f }"><span :class="cls(f.since_base_pct)">{{ signed(f.since_base_pct, 1) }}%</span></template>
          </Column>
          <Column field="weight" header="权重%" sortable>
            <template #body="{ data: f }">{{ f.weight.toFixed(1) }}</template>
          </Column>
        </DataTable>
      </section>
    </template>
  </div>
</template>

<style scoped>
.etf { display: flex; flex-direction: column; gap: 12px; }
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.head > div:first-child { flex: 1 1 480px; }
h2 { margin: 0 0 4px; font-size: 18px; }
h3 { margin: 0 0 8px; font-size: 15px; }
h3 .small { font-weight: normal; margin-left: 6px; }
.small { font-size: 12px; line-height: 1.6; }
.controls { display: flex; align-items: center; gap: 12px; }
.date { margin-left: 6px; font: inherit; padding: 4px 6px; border: 1px solid var(--border); border-radius: 6px; }
.sum { font-size: 13px; line-height: 1.8; font-variant-numeric: tabular-nums; }
.movers { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 6px 0 0; }
.bad { color: var(--up); }
.index { color: #2563eb; }
.algo ol { margin: 8px 0; padding-left: 20px; font-size: 13px; line-height: 1.7; }
.algo li { margin-bottom: 8px; }
.algo li p { margin: 2px 0 0; color: var(--muted); font-size: 12px; }
.algo .f { margin: 4px 0; padding: 6px 10px; background: #f6f7f9; border-radius: 6px; font-family: "Times New Roman", "Songti SC", serif;
           font-size: 15px; font-style: italic; }
.algo .f sub { font-size: 11px; }
.example { margin: 6px 0 0; padding: 8px 10px; background: #eef4ff; border-radius: 6px; line-height: 1.8; font-variant-numeric: tabular-nums; }
p.card { margin: 0; }
</style>
