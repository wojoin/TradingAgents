<script lang="ts">
import { api as sectorApi, type MarketCrowding as Crowding, type MarketSectors as Sectors, type MarketValuation as Valuation } from '../api'
// One request per (days, day) and per day, shared by every card on the page.
const sectorCache = new Map<string, Promise<Sectors>>()
const valuationCache = new Map<string, Promise<Valuation>>()
function once<T>(cache: Map<string, Promise<T>>, key: string, get: () => Promise<T>): Promise<T> {
  if (!cache.has(key)) {
    const p = get()
    p.catch(() => cache.delete(key))
    cache.set(key, p)
  }
  return cache.get(key)!
}
const fetchSectors = (n: number, d: string) => once(sectorCache, `${n}|${d}`, () => sectorApi.marketSectors(n, d))
const crowdCache = new Map<string, Promise<Crowding>>()
const fetchCrowding = (d: string) => once(crowdCache, d, () => sectorApi.marketCrowding(d))
const fetchValuation = (d: string) => once(valuationCache, d, () => sectorApi.marketValuation(d))
</script>

<script setup lang="ts">
// Sectors and valuation, as cards in the stats grid: the 申万一级 industries' heat map over the
// last 10 or 20 trading days, their valuation against their own history, the day's main-force
// flow by industry, and the whole market's (申万A指) PE, PB and dividend yield since 2005.
import { computed, ref, watch } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import { formatYuan, type FlowSpan, type IndustryFlow, type MarketCrowding, type MarketRow, type MarketSectors, type MarketValuation } from '../api'
import LineChart, { type Line } from './LineChart.vue'

// ``cards``: which to show (heat, crowd, val, flow, market, erp); all by default.
type Card = 'heat' | 'crowd' | 'val' | 'flow' | 'market' | 'erp'
const props = defineProps<{ rows: MarketRow[]; date: string | null; flowLabel?: string; flowNote?: string; cards?: Card[] }>()
const has = (c: Card) => !props.cards || props.cards.includes(c)
const emit = defineEmits<{ pick: [industry: string] }>()

const UP = '#e5484d'
const DOWN = '#1f9d55'
type Num = number | null | undefined
const signed = (v: Num, d = 2) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(d)}%`)
const cls = (v: Num) => (!v ? '' : v > 0 ? 'up' : 'down')
function stored<T>(key: string, fallback: T, ok: (v: unknown) => boolean) {
  let v = fallback
  try {
    const s = JSON.parse(localStorage.getItem(key) || 'null')
    if (ok(s)) v = s as T
  } catch {
    /* storage blocked or bad: the default */
  }
  const r = ref(v)
  watch(r, (x) => {
    try {
      localStorage.setItem(key, JSON.stringify(x))
    } catch {
      /* storage blocked */
    }
  })
  return r
}

// ---- 行业轮动热力图 + 行业估值 (one request) ----
const span = stored<10 | 20>('market.heatDays', 20, (v) => v === 10 || v === 20)
const SPANS = [{ value: 10, label: '近10日' }, { value: 20, label: '近20日' }]
const sec = ref<MarketSectors | null>(null)
const secError = ref('')
const secLoading = ref(false)
watch([span, () => props.date], async ([n, d]) => {
  if (!d || !(has('heat') || has('val'))) return
  secLoading.value = true
  secError.value = ''
  try {
    const r = await fetchSectors(n, d)
    if (span.value === n && props.date === d) sec.value = r
  } catch (e) {
    secError.value = e instanceof Error ? e.message : String(e)
  } finally {
    secLoading.value = false
  }
}, { immediate: true })
const mmdd = (d: string) => d.slice(5)
// Red up, green down, stronger with the size of the move (full at ±4%).
function heat(v: Num) {
  if (v === null || v === undefined) return { background: '#f6f7f9' }
  const a = Math.min(Math.abs(v) / 4, 1) * 0.85 + 0.08
  const rgb = v >= 0 ? '229, 72, 77' : '31, 157, 85'
  return { background: `rgba(${rgb}, ${a.toFixed(2)})`, color: a > 0.55 ? '#fff' : '#1f2933' }
}

// Valuation against its own history: low under 20%, high over 80%.
const rankTag = (r: Num) => (r === null || r === undefined ? '' : r <= 20 ? 'low' : r >= 80 ? 'high' : '')

// ---- 行业资金流: 当日 / 5日 / 10日, summed by industry on the server ----
const flowLevel = ref<'sw1' | 'sw2'>('sw1')
const LEVELS = [{ value: 'sw1', label: '一级' }, { value: 'sw2', label: '二级' }]
const flowSpan = stored<FlowSpan>('market.flowSpan', '1d', (v) => v === '1d' || v === '5d' || v === '10d')
const FLOW_SPANS = [{ value: '1d', label: '当日' }, { value: '5d', label: '5日' }, { value: '10d', label: '10日' }]
const flowData = ref<IndustryFlow | null>(null)
const flowError = ref('')
const flowLoading = ref(false)
watch([flowSpan, () => props.date], async ([sp, d]) => {
  if (!d || !has('flow')) return
  flowLoading.value = true
  flowError.value = ''
  try {
    const r = await sectorApi.industryFlow(sp, d)
    if (flowSpan.value === sp && props.date === d) flowData.value = r
  } catch (e) {
    flowError.value = e instanceof Error ? e.message : String(e)
  } finally {
    flowLoading.value = false
  }
}, { immediate: true })
const flows = computed(() => {
  const f = flowData.value
  const list = ((flowLevel.value === 'sw1' ? f?.sw1 : f?.sw2) || []).map((x) => ({ name: x.name, v: x.flow ?? 0 }))
  const ins = list.filter((x) => x.v > 0).slice(0, 10)
  const outs = list.filter((x) => x.v < 0).reverse().slice(0, 10)
  const max = Math.max(1, ...ins.map((x) => x.v), ...outs.map((x) => -x.v))
  return { any: !!f?.available, total: f?.total ?? 0, ins, outs, max,
           inCount: list.filter((x) => x.v > 0).length, outCount: list.filter((x) => x.v < 0).length }
})
const spanLabel = computed(() => FLOW_SPANS.find((x) => x.value === flowSpan.value)?.label)

// ---- 行业拥挤度 ----
const crowd = ref<MarketCrowding | null>(null)
const crowdError = ref('')
watch(() => props.date, async (d) => {
  if (!d || !has('crowd')) return
  crowdError.value = ''
  try {
    const r = await fetchCrowding(d)
    if (props.date === d) crowd.value = r
  } catch (e) {
    crowdError.value = e instanceof Error ? e.message : String(e)
  }
}, { immediate: true })
const crowdTag = (v: number) => (v >= 80 ? { label: '拥挤', cls: 'high' } : v <= 20 ? { label: '冷清', cls: 'low' } : null)
const crowdHot = computed(() => (crowd.value?.industries || []).filter((x) => x.crowd >= 80).map((x) => x.name))

// ---- 全市场估值 (申万A指) ----
const val = ref<MarketValuation | null>(null)
const valError = ref('')
watch(() => props.date, async (d) => {
  if (!d || !(has('market') || has('erp'))) return
  valError.value = ''
  try {
    const r = await fetchValuation(d)
    if (props.date === d) val.value = r
  } catch (e) {
    valError.value = e instanceof Error ? e.message : String(e)
  }
}, { immediate: true })
type Metric = 'pe' | 'pb' | 'dy'
const METRICS = [{ value: 'pe', label: '市盈率' }, { value: 'pb', label: '市净率' }, { value: 'dy', label: '股息率' }]
const metric = stored<Metric>('market.valMetric', 'pe', (v) => v === 'pe' || v === 'pb' || v === 'dy')
const YEARS = [{ value: 1, label: '近1年' }, { value: 3, label: '近3年' }, { value: 5, label: '近5年' }, { value: 10, label: '近10年' }, { value: 0, label: '2005年至今' }]
const years = stored<number>('market.valYears', 10, (v) => [0, 1, 3, 5, 10].includes(v as number))
const valDays = computed(() => {
  const all = val.value?.days || []
  if (!all.length || !years.value) return all
  const last = all[all.length - 1].date
  const from = `${Number(last.slice(0, 4)) - years.value}${last.slice(4)}`
  return all.filter((d) => d.date > from)
})
const valStats = computed(() => {
  const xs = valDays.value.map((d) => d[metric.value]).filter((v): v is number => typeof v === 'number' && v > 0)
  if (!xs.length) return null
  const now = xs[xs.length - 1]
  const sorted = [...xs].sort((a, b) => a - b)
  const median = sorted[Math.floor(sorted.length / 2)]
  return { now, rank: (xs.filter((v) => v <= now).length / xs.length) * 100, min: sorted[0], max: sorted[sorted.length - 1], median }
})
const fmtMetric = (v: number) => (metric.value === 'dy' ? `${v.toFixed(2)}%` : v.toFixed(2))
const valLines = computed<Line[]>(() => {
  const name = METRICS.find((m) => m.value === metric.value)!.label
  const pts = valDays.value.flatMap((d) => { const v = d[metric.value]; return typeof v === 'number' && v > 0 ? [{ time: d.date, value: v }] : [] })
  const med = valStats.value?.median
  return [
    { name, color: '#2563eb', points: pts },
    ...(med ? [{ name: '区间中位数', color: '#9aa4b2', points: pts.map((p) => ({ time: p.time, value: med })) }] : []),
  ]
})
// High PE / PB is expensive; a high dividend yield is cheap.
const valMood = computed(() => {
  const s = valStats.value
  if (!s) return ''
  const r = metric.value === 'dy' ? 100 - s.rank : s.rank
  return r <= 20 ? '偏低估' : r >= 80 ? '偏高估' : r <= 40 ? '略低于中枢' : r >= 60 ? '略高于中枢' : '处于中枢附近'
})

// ---- 股债性价比: the earnings yield (1 / PE) less the 10-year bond yield ----
const erpYears = stored<number>('market.erpYears', 10, (v) => [0, 1, 3, 5, 10].includes(v as number))
const erpDays = computed(() => {
  const all = (val.value?.days || []).filter((d) => d.erp !== null)
  if (!all.length || !erpYears.value) return all
  const last = all[all.length - 1].date
  const from = `${Number(last.slice(0, 4)) - erpYears.value}${last.slice(4)}`
  return all.filter((d) => d.date > from)
})
const erpStats = computed(() => {
  const ds = erpDays.value
  const last = ds[ds.length - 1]
  if (!last || last.erp === null) return null
  const xs = ds.map((d) => d.erp as number)
  const sorted = [...xs].sort((a, b) => a - b)
  const rank = (xs.filter((v) => v <= last.erp!).length / xs.length) * 100
  const mood = rank >= 80 ? '股票相对债券很便宜' : rank >= 60 ? '股票相对偏便宜' : rank <= 20 ? '股票相对债券很贵' : rank <= 40 ? '股票相对偏贵' : '处于中枢附近'
  return { last, ey: last.pe ? 100 / last.pe : null, rank, median: sorted[Math.floor(sorted.length / 2)], mood,
           min: sorted[0], max: sorted[sorted.length - 1] }
})
const pp = (v: number) => `${v.toFixed(2)}%`
const erpLines = computed<Line[]>(() => {
  const pts = erpDays.value.map((d) => ({ time: d.date, value: d.erp as number }))
  const med = erpStats.value?.median
  return [
    { name: '股债性价比', color: '#7c3aed', points: pts },
    ...(med !== undefined ? [{ name: '区间中位数', color: '#9aa4b2', points: pts.map((p) => ({ time: p.time, value: med })) }] : []),
  ]
})
</script>

<template>
  <!-- 行业轮动热力图 -->
  <section v-if="has('heat')" class="card wide">
    <div class="head">
      <h3>行业轮动热力图</h3>
      <SelectButton v-model="span" :options="SPANS" option-label="label" option-value="value" :allow-empty="false" size="small" />
    </div>
    <p v-if="secError" class="bad small">{{ secError }}</p>
    <p v-else-if="secLoading && !sec" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small sub">申万一级行业指数每日涨跌幅（申万官方，市值加权），按区间累计涨幅排序；颜色越深涨跌越大。连续变红的是资金正在流入的方向，由红转绿说明轮动切换。点行业名筛选上方表格。
      <template v-if="sec && date && sec.as_of !== date"> 申万数据截至 {{ sec.as_of }}。</template>
      <span v-if="sec?.note" class="bad">{{ sec.note }}</span></p>
    <div v-if="sec" class="heat-wrap">
      <table class="heat">
        <thead>
          <tr>
            <th class="nm">行业</th>
            <th class="cum">{{ sec.days }}日累计</th>
            <th class="cum">5日</th>
            <th v-for="d in sec.dates" :key="d">{{ mmdd(d) }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in sec.industries" :key="r.code">
            <td class="nm"><a class="link" @click="emit('pick', r.name)">{{ r.name }}</a></td>
            <td class="cum" :class="cls(r.cum)">{{ signed(r.cum, 1) }}</td>
            <td class="cum" :class="cls(r.cum5)">{{ signed(r.cum5, 1) }}</td>
            <td v-for="(v, i) in r.pct" :key="i" class="cell" :style="heat(v)" :title="`${r.name} ${sec.dates[i]} ${signed(v)}`">
              {{ v === null ? '' : v.toFixed(1) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <!-- 行业拥挤度 -->
  <section v-if="has('crowd')" class="card wide">
    <div class="head">
      <h3>行业拥挤度</h3>
      <span class="muted small">{{ crowd?.as_of }}</span>
    </div>
    <p v-if="crowdError" class="bad small">{{ crowdError }}</p>
    <p v-else-if="crowd" class="sum">
      <template v-if="crowdHot.length">拥挤（≥80）：<b class="hot">{{ crowdHot.join('、') }}</b></template>
      <template v-else>当前没有拥挤（≥80）的行业</template>
    </p>
    <p class="muted small sub">申万一级行业近 {{ crowd?.smooth ?? 5 }} 日平均的<b>成交额占比</b>和<b>换手率</b>，各自在 {{ crowd?.since?.slice(0, 4) || '2021' }} 年以来的历史分位，拥挤度为两者平均。
      <span class="tag high">拥挤</span> ≥80：交易过热，资金一致性高，<b>易出现快速回撤</b>，尤其是已大涨的行业；<span class="tag low">冷清</span> ≤20：关注度低，可能被低估或正被资金遗弃。
      <span v-if="crowd?.note" class="bad">{{ crowd.note }}</span></p>
    <DataTable v-if="crowd" :value="crowd.industries" data-key="name" sort-field="crowd" :sort-order="-1" scrollable scroll-height="380px"
               size="small" striped-rows removable-sort class="val">
      <Column field="name" header="行业" sortable style="min-width: 84px">
        <template #body="{ data: r }"><a class="link" @click="emit('pick', r.name)">{{ r.name }}</a></template>
      </Column>
      <Column field="crowd" header="拥挤度" sortable header-class="nr" body-class="nr" style="min-width: 150px">
        <template #body="{ data: r }">
          <span class="cbar"><span class="cfill" :style="{ width: `${r.crowd}%`, background: r.crowd >= 80 ? '#c2410c' : r.crowd <= 20 ? '#1d4ed8' : '#9aa4b2' }" /></span>
          <b>{{ r.crowd.toFixed(0) }}</b>
          <span v-if="crowdTag(r.crowd)" class="tag" :class="crowdTag(r.crowd)!.cls">{{ crowdTag(r.crowd)!.label }}</span>
        </template>
      </Column>
      <Column field="share5" header="成交占比" sortable header-class="nr" body-class="nr">
        <template #body="{ data: r }">{{ r.share5 === null ? '—' : `${r.share5.toFixed(2)}%` }}
          <span v-if="r.share5 !== null && r.share5_20d !== null" class="small" :class="cls(r.share5 - r.share5_20d)">{{ r.share5 >= r.share5_20d ? '↑' : '↓' }}</span></template>
      </Column>
      <Column field="share_rank" header="占比分位" sortable header-class="nr" body-class="nr">
        <template #body="{ data: r }"><span class="rank" :class="rankTag(r.share_rank) === 'low' ? 'low' : rankTag(r.share_rank) === 'high' ? 'high' : ''">{{ r.share_rank.toFixed(0) }}%</span></template>
      </Column>
      <Column field="turnover5" header="换手率" sortable header-class="nr" body-class="nr">
        <template #body="{ data: r }">{{ r.turnover5 === null ? '—' : `${r.turnover5.toFixed(2)}%` }}</template>
      </Column>
      <Column field="turnover_rank" header="换手分位" sortable header-class="nr" body-class="nr">
        <template #body="{ data: r }"><span class="rank" :class="rankTag(r.turnover_rank) === 'low' ? 'low' : rankTag(r.turnover_rank) === 'high' ? 'high' : ''">{{ r.turnover_rank.toFixed(0) }}%</span></template>
      </Column>
      <Column field="cum20" header="20日涨幅" sortable header-class="nr" body-class="nr">
        <template #body="{ data: r }"><span :class="cls(r.cum20)">{{ signed(r.cum20, 1) }}</span></template>
      </Column>
    </DataTable>
  </section>

  <!-- 全市场估值 -->
  <section v-if="has('market')" class="card">
    <div class="head">
      <h3>全市场估值</h3>
      <Select v-model="years" :options="YEARS" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <SelectButton v-model="metric" :options="METRICS" option-label="label" option-value="value" :allow-empty="false" size="small" class="spans" />
    <p v-if="valError" class="bad small">{{ valError }}</p>
    <p v-else-if="valStats" class="sum">
      {{ val?.as_of }} 申万A指{{ METRICS.find((m) => m.value === metric)?.label }} <b>{{ fmtMetric(valStats.now) }}</b>，
      处于{{ YEARS.find((y) => y.value === years)?.label }} <b>{{ valStats.rank.toFixed(0) }}%</b> 分位，{{ valMood }}
      <span class="muted">（最低 {{ fmtMetric(valStats.min) }} · 中位 {{ fmtMetric(valStats.median) }} · 最高 {{ fmtMetric(valStats.max) }}）</span>
    </p>
    <p class="muted small sub">申万A指覆盖全部 A 股，按市值加权。市盈率、市净率分位越低越便宜；股息率相反，越高越便宜。估值分位适合判断长期位置，不适合择时短线。
      <span v-if="val?.note" class="bad">{{ val.note }}</span></p>
    <LineChart v-if="val" :lines="valLines" :format="fmtMetric" :height="200" />
  </section>
  <!-- 股债性价比 -->
  <section v-if="has('erp')" class="card">
    <div class="head">
      <h3>股债性价比</h3>
      <Select v-model="erpYears" :options="YEARS" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="valError" class="bad small">{{ valError }}</p>
    <p v-else-if="erpStats" class="sum">
      {{ erpStats.last.date }}：<b>{{ pp(erpStats.last.erp!) }}</b> = 盈利收益率 {{ erpStats.ey === null ? '—' : pp(erpStats.ey) }}
      − 10年国债 {{ erpStats.last.y10 === null ? '—' : pp(erpStats.last.y10) }}，
      处于{{ YEARS.find((y) => y.value === erpYears)?.label }} <b>{{ erpStats.rank.toFixed(0) }}%</b> 分位，{{ erpStats.mood }}
      <span class="muted">（最低 {{ pp(erpStats.min) }} · 中位 {{ pp(erpStats.median) }} · 最高 {{ pp(erpStats.max) }}）</span>
    </p>
    <p class="muted small sub">申万A指的盈利收益率（1 ÷ 市盈率）减去 10 年期国债收益率，即买股票比买国债多拿的「风险溢价」。
      分位越高股票相对债券越便宜，历史上高位（≥80%）多对应市场底部区域，低位（≤20%）多对应顶部区域；适合判断长期位置。</p>
    <LineChart v-if="val" :lines="erpLines" :format="pp" :height="200" />
  </section>

  <!-- 行业估值 -->
  <section v-if="has('val')" class="card">
    <div class="head">
      <h3>行业估值</h3>
      <span class="muted small">{{ sec?.as_of }}</span>
    </div>
    <p class="muted small sub">申万一级行业的市盈率、市净率和股息率；分位为今天的值在 {{ sec?.since?.slice(0, 4) || '2021' }} 年以来每天数值中的位置，越低越便宜。
      <span class="tag low">低</span> 分位 ≤20%，<span class="tag high">高</span> 分位 ≥80%。不同行业估值水平天然不同，宜看分位而非绝对值。</p>
    <DataTable v-if="sec" :value="sec.industries" data-key="code" sort-field="pe_rank" :sort-order="1" scrollable scroll-height="360px"
               size="small" striped-rows removable-sort class="val">
      <Column field="name" header="行业" sortable style="min-width: 84px" />
      <Column field="pe" header="市盈率" sortable header-class="nr" body-class="nr">
        <template #body="{ data }">{{ data.pe?.toFixed(1) ?? '—' }}</template>
      </Column>
      <Column field="pe_rank" header="PE分位" sortable header-class="nr" body-class="nr">
        <template #body="{ data }"><span class="rank" :class="rankTag(data.pe_rank)">{{ data.pe_rank === null ? '—' : `${data.pe_rank.toFixed(0)}%` }}</span></template>
      </Column>
      <Column field="pb" header="市净率" sortable header-class="nr" body-class="nr">
        <template #body="{ data }">{{ data.pb?.toFixed(2) ?? '—' }}</template>
      </Column>
      <Column field="pb_rank" header="PB分位" sortable header-class="nr" body-class="nr">
        <template #body="{ data }"><span class="rank" :class="rankTag(data.pb_rank)">{{ data.pb_rank === null ? '—' : `${data.pb_rank.toFixed(0)}%` }}</span></template>
      </Column>
      <Column field="dy" header="股息率" sortable header-class="nr" body-class="nr">
        <template #body="{ data }">{{ data.dy === null ? '—' : `${data.dy.toFixed(2)}%` }}</template>
      </Column>
    </DataTable>
  </section>

  <!-- 行业资金流 -->
  <section v-if="has('flow')" class="card">
    <div class="head">
      <h3>行业资金流</h3>
      <span class="btns">
        <SelectButton v-model="flowSpan" :options="FLOW_SPANS" option-label="label" option-value="value" :allow-empty="false" size="small" />
        <SelectButton v-model="flowLevel" :options="LEVELS" option-label="label" option-value="value" :allow-empty="false" size="small" />
      </span>
    </div>
    <p v-if="flowError" class="bad small">{{ flowError }}</p>
    <p v-else-if="flowLoading && !flowData" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中（5日、10日首次需下载全市场排行，约 5 秒）</p>
    <p v-else-if="!flows.any" class="muted small sub">{{ flowData?.note || `${date} 没有资金流数据` }}</p>
    <template v-else>
      <p class="sum">{{ flowData?.date }} {{ spanLabel }}主力净流入合计 <b :class="cls(flows.total)">{{ formatYuan(flows.total, true) }}</b> ·
        流入 {{ flows.inCount }} 个行业，流出 {{ flows.outCount }} 个</p>
      <p class="muted small sub">东方财富主力（超大单 + 大单）净流入，各股求和到申万行业；5日、10日只有最近一个交易日能取到。
        <b>多日持续净流入</b>比单日更可靠。</p>
      <div class="flow">
        <div>
          <div class="muted small">净流入前 10</div>
          <div v-for="x in flows.ins" :key="x.name" class="fbar">
            <span class="fname" :title="x.name">{{ x.name }}</span>
            <span class="ftrack"><span class="ffill" :style="{ width: `${(x.v / flows.max) * 100}%`, background: UP }" /></span>
            <span class="fval up">{{ formatYuan(x.v, true) }}</span>
          </div>
        </div>
        <div>
          <div class="muted small">净流出前 10</div>
          <div v-for="x in flows.outs" :key="x.name" class="fbar">
            <span class="fname" :title="x.name">{{ x.name }}</span>
            <span class="ftrack"><span class="ffill" :style="{ width: `${(-x.v / flows.max) * 100}%`, background: DOWN }" /></span>
            <span class="fval down">{{ formatYuan(x.v, true) }}</span>
          </div>
        </div>
      </div>
    </template>
  </section>

</template>

<style scoped>
.wide { grid-column: 1 / -1; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h3 { margin: 0; font-size: 15px; }
.sum { margin: 8px 0; font-size: 13px; line-height: 1.6; font-variant-numeric: tabular-nums; }
.small { font-size: 12px; }
.sub { margin: 6px 0; }
.bad { color: var(--up); }
.range { width: 130px; }
.cbar { display: inline-block; width: 60px; height: 8px; background: #f1f3f6; border-radius: 4px; overflow: hidden; margin-right: 6px; vertical-align: middle; }
.cfill { display: block; height: 100%; border-radius: 4px; }
.hot { color: #c2410c; }
.btns { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.spans { margin-top: 8px; }
.link { cursor: pointer; }
.link:hover { color: var(--up); }

.heat-wrap { overflow-x: auto; margin-top: 6px; }
.heat { border-collapse: separate; border-spacing: 2px; font-size: 12px; font-variant-numeric: tabular-nums; }
.heat th { font-weight: 500; color: var(--muted); padding: 2px 4px; white-space: nowrap; }
.heat td { padding: 3px 4px; text-align: center; white-space: nowrap; }
.heat .nm { position: sticky; left: 0; background: #fff; text-align: left; z-index: 1; padding-right: 8px; }
.heat .cum { text-align: right; padding: 0 6px; font-weight: 600; }
.heat .cell { min-width: 34px; border-radius: 3px; }

.tag, .rank { font-size: 12px; padding: 0 5px; border-radius: 4px; }
.low { background: #e0ecff; color: #1d4ed8; }
.high { background: #fff1e6; color: #c2410c; }
:deep(.val th.nr), :deep(.val td.nr) { text-align: right; font-variant-numeric: tabular-nums; }
:deep(.val th.nr .p-datatable-column-header-content) { justify-content: flex-end; }
:deep(.val td) { white-space: nowrap; }

.flow { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 6px; }
.fbar { display: grid; grid-template-columns: 88px 1fr 76px; align-items: center; gap: 6px; font-size: 12px; margin-top: 4px; }
.fname { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ftrack { height: 10px; background: #f6f7f9; border-radius: 3px; overflow: hidden; }
.ffill { display: block; height: 100%; border-radius: 3px; }
.fval { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
@media (max-width: 760px) { .flow { grid-template-columns: 1fr; } }
</style>
