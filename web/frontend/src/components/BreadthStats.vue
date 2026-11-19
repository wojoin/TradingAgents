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
import { api, formatYuan, type BreadthDay, type MarketBoards, type MarketBreadth } from '../api'
import { RANGES, rangeRef } from '../statsRange'
import LineChart, { type Line } from './LineChart.vue'

// ``cards``: which to show (mood, prem, promo, height, size, highs, ma, boards, conc, trin, mcl, msi, thrust, adr); all by default.
type Card = 'mood' | 'prem' | 'promo' | 'height' | 'size' | 'highs' | 'ma' | 'boards' | 'conc' | 'trin' | 'mcl' | 'thrust' | 'adr' | 'msi'
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

// ---- 分板块表现: the day's boards, and each board's median change compounded over the span ----
const BOARDS = ['主板', '创业板', '科创板', '北交所'] as const
const BOARD_COLORS: Record<string, string> = { 主板: '#2563eb', 创业板: '#f59e0b', 科创板: '#65a30d', 北交所: '#db2777' }
const bd = useBreadth('market.boardRange', 'boards')
const boardDay = ref<MarketBoards | null>(null)
const boardError = ref('')
watch(() => props.date, async (d) => {
  if (!d || !has('boards')) return
  boardError.value = ''
  try {
    const r = await api.marketBoards(d)
    if (props.date === d) boardDay.value = r
  } catch (e) {
    boardError.value = e instanceof Error ? e.message : String(e)
  }
}, { immediate: true })
const boardLines = computed<Line[]>(() => BOARDS.map((b) => {
  let f = 1
  return {
    name: b, color: BOARD_COLORS[b],
    points: bd.days.value.flatMap((d) => {
      const v = d[`board_${b}`]
      if (v === null || v === undefined) return []
      f *= 1 + v / 100
      return [{ time: d.date, value: (f - 1) * 100 }]
    }),
  }
}))

// ---- 成交集中度: the busiest stocks' share of the amount traded ----
const conc = useBreadth('market.concRange', 'conc')
const concLines = computed<Line[]>(() => [
  { name: '前100只', color: '#7c3aed', points: pts(conc.days.value, (d) => d.conc100) },
  { name: '前5%', color: '#f59e0b', points: pts(conc.days.value, (d) => d.conc5pct) },
])
const concSummary = computed(() => {
  const ds = conc.days.value.filter((d) => d.conc100 !== null)
  if (!ds.length) return null
  const xs = ds.map((d) => d.conc100 as number)
  const last = ds[ds.length - 1]
  return { last, avg: mean(xs), max: Math.max(...xs), min: Math.min(...xs),
           rank: (xs.filter((v) => v <= (last.conc100 as number)).length / xs.length) * 100 }
})

// ---- TRIN (Arms index): TRIN_额 and TRIN_量, daily or their 10-day average ----
const trin = useBreadth('market.trinRange', 'trin')
const TRIN_VIEWS = [{ value: 'avg', label: '10日均' }, { value: 'day', label: '日值' }]
const trinView = ref<'avg' | 'day'>('avg')
const trinLines = computed<Line[]>(() => {
  const avg = trinView.value === 'avg'
  const ds = trin.days.value
  const amt = pts(ds, (d) => (avg ? d.trin_amt10 : d.trin_amt))
  return [
    { name: avg ? 'TRIN_额 10日均' : 'TRIN_额', color: '#2563eb', points: amt },
    { name: avg ? 'TRIN_量 10日均' : 'TRIN_量', color: '#f59e0b', points: pts(ds, (d) => (avg ? d.trin_vol10 : d.trin_vol)) },
    { name: '1（平衡）', color: '#c0c6cf', points: amt.map((p) => ({ time: p.time, value: 1 })) },
  ]
})
const trinMood = (r: Num) => (r === null || r === undefined ? '' : r >= 80 ? '偏高：下跌股吸走更多资金，偏空' : r <= 20 ? '偏低：资金集中在上涨股' : '处于常态区间')

// ---- 广度推力 (Zweig breadth thrust) ----
const thrust = useBreadth('market.thrustRange', 'thrust')
const thrustLines = computed<Line[]>(() => {
  const p = pts(thrust.days.value, (d) => d.thrust)
  return [
    { name: '广度推力', color: '#7c3aed', points: p },
    { name: '0.615 推力线', color: UP, points: p.map((x) => ({ time: x.time, value: 0.615 })) },
    { name: '0.40 低位线', color: DOWN, points: p.map((x) => ({ time: x.time, value: 0.4 })) },
  ]
})
const thrustSignals = computed(() => thrust.days.value.filter((d) => d.thrust_signal).map((d) => d.date))
const thrustZone = (v: Num) => (v === null || v === undefined ? '' : v >= 0.615 ? '推力区：普涨爆发' : v <= 0.4 ? '低位区：普跌、情绪低迷，等待推力' : '中性区')

// ---- 涨跌比 ADR 与 绝对广量 ABI ----
const adr = useBreadth('market.adrRange', 'adr')
const adrLines = computed<Line[]>(() => {
  const p = pts(adr.days.value, (d) => d.adr10)
  return [
    { name: 'ADR 10日均', color: '#2563eb', points: p },
    { name: '1（涨跌相当）', color: '#c0c6cf', points: p.map((x) => ({ time: x.time, value: 1 })) },
  ]
})
const abiLines = computed<Line[]>(() => [
  { name: 'ABI', color: '#f59e0b', bars: true, points: pts(adr.days.value, (d) => d.abi) },
  { name: 'ABI 10日均', color: '#7c3aed', points: pts(adr.days.value, (d) => d.abi10) },
])

// ---- 麦克连: the oscillator as bars, the summation index as a line ----
const mcl = useBreadth('market.mclRange', 'mcl')
const mclLines = computed<Line[]>(() => [{
  name: '麦克连震荡指标', color: UP, bars: true,
  points: mcl.days.value.flatMap((d) => (d.mcl_osc === null ? [] : [{ time: d.date, value: d.mcl_osc, color: d.mcl_osc >= 0 ? UP : DOWN }])),
}])
// ---- MSI 麦克莱伦累积指数 ----
const msi = useBreadth('market.msiRange', 'msi')
const msiLines = computed<Line[]>(() => {
  const p = pts(msi.days.value, (d) => d.mcl_sum)
  return [
    { name: 'MSI', color: '#7c3aed', points: p },
    { name: '0 轴', color: '#c0c6cf', points: p.map((x) => ({ time: x.time, value: 0 })) },
  ]
})
const msiCrosses = computed(() => msi.days.value.filter((d) => d.msi_cross).map((d) => ({ date: d.date, up: (d.msi_cross ?? 0) > 0 })))
const msiSince = computed(() => {
  const ds = msi.days.value.filter((d) => d.mcl_sum !== null)
  if (!ds.length) return null
  const last = ds[ds.length - 1]
  let n = 0
  for (let i = ds.length - 1; i >= 0 && Math.sign(ds[i].mcl_sum as number) === Math.sign(last.mcl_sum as number); i--) n++
  return { last, days: n, all: n === ds.length }
})
const mclTurn = computed(() => {
  const ds = mcl.days.value.filter((d) => d.mcl_osc !== null)
  for (let i = ds.length - 1; i > 0; i--) {
    if (Math.sign(ds[i].mcl_osc as number) !== Math.sign(ds[i - 1].mcl_osc as number)) {
      return { date: ds[i].date, up: (ds[i].mcl_osc as number) > 0 }
    }
  }
  return null
})

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
    { name: '净值（新高 − 新低）', color: '#7c3aed',
      points: pts(highs.days.value, (d) => { const hi = n === 60 ? d.nh60 : d.nh250; const lo = n === 60 ? d.nl60 : d.nl250
        return hi === null || lo === null ? null : hi - lo }) },
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
  { name: 'P20 站上20日线', color: '#f59e0b', points: pts(mas.days.value, (d) => d.ma20) },
  { name: 'P60 站上60日线', color: '#2563eb', points: pts(mas.days.value, (d) => d.ma60) },
  { name: 'P250 站上250日线', color: '#7c3aed', points: pts(mas.days.value, (d) => d.ma250) },
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

  <!-- 分板块表现 -->
  <section v-if="has('boards')" class="card">
    <div class="head">
      <h3>分板块表现</h3>
      <Select v-model="bd.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="boardError" class="bad small">{{ boardError }}</p>
    <table v-if="boardDay" class="btable">
      <thead><tr><th>{{ boardDay.date.slice(5) }}</th><th class="nr">家数</th><th class="nr">涨 / 跌</th><th class="nr">中位涨幅</th>
        <th class="nr">涨停 / 跌停</th><th class="nr">成交额</th><th class="nr">成交占比</th></tr></thead>
      <tbody>
        <tr v-for="b in boardDay.boards" :key="b.board">
          <td><i class="dot" :style="{ background: BOARD_COLORS[b.board] }" />{{ b.board }}</td>
          <td class="nr">{{ b.count }}</td>
          <td class="nr"><span class="up">{{ b.up }}</span> / <span class="down">{{ b.down }}</span></td>
          <td class="nr" :class="cls(b.median)">{{ signed(b.median) }}</td>
          <td class="nr"><span class="up">{{ b.limit_up }}</span> / <span class="down">{{ b.limit_down }}</span></td>
          <td class="nr">{{ formatYuan(b.amount) }}</td>
          <td class="nr">{{ b.amount_share === null ? '—' : `${b.amount_share.toFixed(1)}%` }}</td>
        </tr>
      </tbody>
    </table>
    <p class="muted small">主板（沪深 60、00 开头）、创业板（300/301）、科创板（688/689）、北交所（4、8、920 开头）分开统计；下图为各板块中位涨幅的区间累计。
      创业板、科创板、北交所领涨说明风险偏好高，主板领涨多为防御或权重行情。</p>
    <LineChart v-if="bd.data.value" :lines="boardLines" :format="(v) => signed(v, 1)" :height="180" pick />
  </section>

  <!-- 成交集中度 -->
  <section v-if="has('conc')" class="card">
    <div class="head">
      <h3>成交集中度</h3>
      <Select v-model="conc.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="conc.error.value" class="bad small">{{ conc.error.value }}</p>
    <p v-else-if="concSummary" class="sum">
      {{ concSummary.last.date }}：成交额最大的 100 只占全市场 <b>{{ pct(concSummary.last.conc100) }}</b>，前 5% 的股票占
      <b>{{ pct(concSummary.last.conc5pct) }}</b>
      <template v-if="conc.days.value.length > 1">；区间 {{ pct(concSummary.min) }}–{{ pct(concSummary.max) }}，当前处于 {{ concSummary.rank.toFixed(0) }}% 分位</template>
    </p>
    <p v-else-if="conc.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small">每天成交额最大的 100 只股票（以及前 5% 的股票）成交额占全市场的比例。占比上升说明资金向少数股票集中、抱团，
      常见于存量博弈或行情后期；占比下降说明交易分散到更多股票，普涨行情多如此。</p>
    <LineChart v-if="conc.data.value" :lines="concLines" :format="(v) => pct(v)" :height="180" />
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
      {{ highs.last.value?.date }}：创{{ highSpan }}日新高 <b class="up">{{ highLast.hi ?? '—' }}</b> 家，新低 <b class="down">{{ highLast.lo ?? '—' }}</b> 家<template v-if="highLast.hi !== null && highLast.lo !== null">，净值 <b :class="cls(highLast.hi - highLast.lo)">{{ highLast.hi - highLast.lo > 0 ? '+' : '' }}{{ highLast.hi - highLast.lo }}</b></template>
    </p>
    <p v-else-if="highs.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small">收盘价（复权）高于此前 {{ highSpan }} 个交易日每天收盘的为新高，低于的为新低。新高多于新低（净值为正）说明市场在走强；净值由负转正、或新低家数开始减少，是广度转好的早期信号；指数创新高而新高家数减少，是上涨面收窄的警示。</p>
    <LineChart v-if="highs.data.value" :lines="highLines" :format="(v) => `${Math.round(v)}`" :height="180" />
  </section>

  <!-- 均线上方占比 -->
  <section v-if="has('ma')" class="card">
    <div class="head">
      <h3>均线上方占比(% of Stocks Above MA)</h3>
      <Select v-model="mas.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="mas.error.value" class="bad small">{{ mas.error.value }}</p>
    <p v-else-if="mas.last.value" class="sum">
      {{ mas.last.value.date }}：P20 <b>{{ pct(mas.last.value.ma20) }}</b>
      <span v-if="maMood(mas.last.value.ma20)" class="muted">（{{ maMood(mas.last.value.ma20) }}）</span> ·
      P60 <b>{{ pct(mas.last.value.ma60) }}</b>
      <span v-if="maMood(mas.last.value.ma60)" class="muted">（{{ maMood(mas.last.value.ma60) }}）</span> ·
      P250 <b>{{ pct(mas.last.value.ma250) }}</b>
      <span v-if="maMood(mas.last.value.ma250)" class="muted">（{{ maMood(mas.last.value.ma250) }}）</span>
    </p>
    <p v-else-if="mas.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small">P20 / P60 / P250：收盘价（复权）高于自身 20 日、60 日、250 日（年线）均线的股票占比。高于 80% 偏热、低于 20% 超跌；20 日线看短期，60 日线看中期，250 日线看长期：年线上方占比极低后回升，常对应中长期底部的构筑。</p>
    <LineChart v-if="mas.data.value" :lines="maLines" :format="(v) => pct(v)" :height="180" />
  </section>

  <!-- TRIN 阿姆氏指标 -->
  <section v-if="has('trin')" class="card">
    <div class="head">
      <h3>TRIN 阿姆氏指标(看资金跟着涨的走还是跌的走)</h3>
      <Select v-model="trin.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <SelectButton v-model="trinView" :options="TRIN_VIEWS" option-label="label" option-value="value" :allow-empty="false" size="small" class="spans" />
    <p v-if="trin.error.value" class="bad small">{{ trin.error.value }}</p>
    <div v-else-if="trin.last.value" class="sum">
      <div class="muted small">{{ trin.last.value.date }}</div>
      <!-- One line each: TRIN_额, then TRIN_量, with its own reading. -->
      <div class="trow">
        <span class="tkey">TRIN_额</span> <b>{{ trin.last.value.trin_amt?.toFixed(2) ?? '—' }}</b>（10日均 {{ trin.last.value.trin_amt10?.toFixed(2) ?? '—' }}，
        近一年 {{ trin.last.value.trin_amt10_rank?.toFixed(0) ?? '—' }}% 分位）<span class="muted small">{{ trinMood(trin.last.value.trin_amt10_rank) }}</span>
      </div>
      <div class="trow">
        <span class="tkey">TRIN_量</span> <b>{{ trin.last.value.trin_vol?.toFixed(2) ?? '—' }}</b>（10日均 {{ trin.last.value.trin_vol10?.toFixed(2) ?? '—' }}，
        近一年 {{ trin.last.value.trin_vol10_rank?.toFixed(0) ?? '—' }}% 分位）<span class="muted small">{{ trinMood(trin.last.value.trin_vol10_rank) }}</span>
      </div>
      <div class="trow small">
        <span class="tkey">涨跌量比</span> 上涨股 ÷ 下跌股 成交额 <b>{{ trin.last.value.ud_amt?.toFixed(2) ?? '—' }}</b>，成交量 <b>{{ trin.last.value.ud_vol?.toFixed(2) ?? '—' }}</b>
        <span class="muted">（小于 1 卖压主导）</span>
      </div>
    </div>
    <p v-else-if="trin.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small">（上涨家数 ÷ 下跌家数）÷（上涨股成交额 ÷ 下跌股成交额），TRIN_量用成交量。小于 1 表示资金更多流向上涨股，大于 1 表示流向下跌股。
      A 股资金常集中在少数上涨股，TRIN 多数时间低于 1，<b>宜看它在近一年中的分位</b>，并结合腾落线、麦克连判断是普涨还是少数股抱团。</p>
    <LineChart v-if="trin.data.value" :lines="trinLines" :format="(v) => v.toFixed(2)" :height="180" />
  </section>

  <!-- MCL 麦克连指标 -->
  <section v-if="has('mcl')" class="card">
    <div class="head">
      <h3>MCL 麦克连指标</h3>
      <Select v-model="mcl.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="mcl.error.value" class="bad small">{{ mcl.error.value }}</p>
    <p v-else-if="mcl.last.value" class="sum">
      {{ mcl.last.value.date }}：震荡指标 <b :class="cls(mcl.last.value.mcl_osc)">{{ mcl.last.value.mcl_osc?.toFixed(1) ?? '—' }}</b>
      （{{ (mcl.last.value.mcl_osc ?? 0) >= 0 ? '0 轴上方，宽度动能向上' : '0 轴下方，宽度动能向下' }}）
      <template v-if="mclTurn">；最近一次{{ mclTurn.up ? '上穿' : '下穿' }} 0 轴在 {{ mclTurn.date }}</template>
    </p>
    <p v-else-if="mcl.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small">每日（上涨 − 下跌）÷（上涨 + 下跌）× 1000，取其 19 日与 39 日指数均线之差。
      MCL 是广度的「速度」，即腾落线的「MACD」：上穿 0 轴宽度转强、下穿转弱，与指数背离是动能衰竭的警示；它的累加见右侧 MSI。</p>
    <LineChart v-if="mcl.data.value" :lines="mclLines" :format="(v) => v.toFixed(1)" :height="180" />
  </section>

  <!-- MSI 麦克莱伦累积指数 -->
  <section v-if="has('msi')" class="card">
    <div class="head">
      <h3>MSI 麦克莱伦累积指数</h3>
      <Select v-model="msi.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="msi.error.value" class="bad small">{{ msi.error.value }}</p>
    <div v-else-if="msiSince" class="sum">
      {{ msiSince.last.date }}：MSI <b :class="cls(msiSince.last.mcl_sum)">{{ msiSince.last.mcl_sum?.toFixed(0) }}</b>
      <span class="muted">（{{ (msiSince.last.mcl_sum ?? 0) >= 0 ? '0 轴上方：中期广度偏强' : '0 轴下方：中期广度承压' }}，已连续 {{ msiSince.days }}{{ msiSince.all ? '+' : '' }} 天）</span>
      <div class="small">区间内穿越 0 轴：
        <template v-if="msiCrosses.length"><span v-for="(c, i) in msiCrosses" :key="c.date"><span :class="c.up ? 'up' : 'down'">{{ c.date }} {{ c.up ? '由负转正' : '由正转负' }}</span><template v-if="i < msiCrosses.length - 1">；</template></span></template>
        <span v-else class="muted">无</span></div>
    </div>
    <p v-else-if="msi.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small">MCL 的逐日累加：MCL 是「速度」，MSI 是「路程」，反映广度动量的中期趋势，比 MCL 平稳。
      <b>由负转正</b>常被视为中期广度由弱转强的信号，持续为负说明中期广度仍承压。按 19 × EMA39 − 9 × EMA19 计算，即从无限远的过去累加，0 轴有意义，不受本地数据起始日影响。</p>
    <LineChart v-if="msi.data.value" :lines="msiLines" :format="(v) => v.toFixed(0)" :height="180" />
  </section>

  <!-- 广度推力 -->
  <section v-if="has('thrust')" class="card">
    <div class="head">
      <h3>广度推力</h3>
      <Select v-model="thrust.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="thrust.error.value" class="bad small">{{ thrust.error.value }}</p>
    <div v-else-if="thrust.last.value" class="sum">
      {{ thrust.last.value.date }}：广度推力 <b>{{ thrust.last.value.thrust?.toFixed(3) ?? '—' }}</b>
      <span class="muted">（{{ thrustZone(thrust.last.value.thrust) }}）</span>
      <div class="small">区间内推力信号：<b v-if="thrustSignals.length" class="up">{{ thrustSignals.join('、') }}</b><span v-else class="muted">无</span></div>
    </div>
    <p v-else-if="thrust.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small">Zweig 广度推力：上涨 ÷（上涨 + 下跌）的 10 日指数均线。<b>10 个交易日内从 0.40 以下升到 0.615 以上</b>即为推力信号，
      表示市场从普跌转为罕见的普涨爆发，历史上多对应重要底部。信号很少（近两年 A 股仅 2 次：2024-12-02、2025-04-14），出现时值得重视。</p>
    <LineChart v-if="thrust.data.value" :lines="thrustLines" :format="(v) => v.toFixed(3)" :height="180" />
  </section>

  <!-- 涨跌比 ADR 与 绝对广量 ABI -->
  <section v-if="has('adr')" class="card">
    <div class="head">
      <h3>涨跌比 ADR · 绝对广量 ABI</h3>
      <Select v-model="adr.range.value" :options="RANGES" option-label="label" option-value="value" size="small" class="range" />
    </div>
    <p v-if="adr.error.value" class="bad small">{{ adr.error.value }}</p>
    <div v-else-if="adr.last.value" class="sum">
      <div class="trow"><span class="tkey">ADR</span> <b :class="(adr.last.value.adr ?? 1) >= 1 ? 'up' : 'down'">{{ adr.last.value.adr?.toFixed(2) ?? '—' }}</b>
        （10日均 {{ adr.last.value.adr10?.toFixed(2) ?? '—' }}，近一年 {{ adr.last.value.adr10_rank?.toFixed(0) ?? '—' }}% 分位）</div>
      <div class="trow"><span class="tkey">ABI</span> <b>{{ adr.last.value.abi?.toFixed(1) ?? '—' }}%</b>
        （10日均 {{ adr.last.value.abi10?.toFixed(1) ?? '—' }}%）</div>
    </div>
    <p v-else-if="adr.loading.value" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p class="muted small"><b>ADR</b> = 上涨家数 ÷ 下跌家数，大于 1 偏强、小于 1 偏弱，比腾落线更灵敏，适合看短期力度；A 股 ADR 中位数略低于 1，宜看分位。
      <b>ABI</b> = |上涨 − 下跌| ÷（上涨 + 下跌），不看方向只看一边倒的程度：极高是普涨或恐慌普跌的极端日，极低是多空胶着、方向不明。</p>
    <LineChart v-if="adr.data.value" :lines="adrLines" :format="(v) => v.toFixed(2)" :height="150" />
    <LineChart v-if="adr.data.value" :lines="abiLines" :format="(v) => `${v.toFixed(1)}%`" :height="120" />
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
.trow { line-height: 1.8; }
.tkey { display: inline-block; min-width: 64px; font-weight: 600; }
.btable { width: 100%; border-collapse: collapse; font-size: 12px; margin: 8px 0 4px; font-variant-numeric: tabular-nums; }
.btable th { font-weight: 500; color: var(--muted); text-align: left; padding: 3px 4px; border-bottom: 1px solid var(--border); white-space: nowrap; }
.btable td { padding: 3px 4px; border-bottom: 1px solid #f1f3f6; white-space: nowrap; }
.btable .nr { text-align: right; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 3px; }
</style>
