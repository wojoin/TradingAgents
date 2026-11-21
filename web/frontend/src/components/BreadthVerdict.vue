<script setup lang="ts">
// 市场广度综合研判: the breadth indicators read in three steps (定趋势 → 找时机 → 验真伪), each
// state judged by how the market did after the same state in the past, and the conclusion built
// up from them. A summary of history, not a forecast.
import { computed, ref, watch } from 'vue'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import { api, type BreadthVerdict, type StatsRange, type StructureDay, type StructureDays, type StructureRange, type VerdictDay, type VerdictHistory } from '../api'
import { rangeRef } from '../statsRange'
import LineChart, { type Line } from './LineChart.vue'

const props = defineProps<{ date: string | null }>()
const data = ref<BreadthVerdict | null>(null)
const error = ref('')
const loading = ref(false)
watch(() => props.date, async (d) => {
  if (!d) return
  loading.value = true
  error.value = ''
  try {
    const v = await api.breadthVerdict(d)
    if (props.date === d) data.value = v
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}, { immediate: true })

// ---- 当日市场结构, day by day: 项目 down the side, a column a day (the newest first) ----
const S_RANGES: { value: StructureRange; label: string }[] = [
  { value: '1d', label: '当日' }, { value: '10d', label: '近10天' }, { value: '30d', label: '近30天' },
  { value: '60d', label: '近60天' }, { value: '6m', label: '半年' }]
const sRange = ref<StructureRange>((() => {
  try {
    const v = localStorage.getItem('market.structureRange')
    return (S_RANGES.some((r) => r.value === v) ? v : '10d') as StructureRange
  } catch {
    return '10d'
  }
})())
watch(sRange, (v) => {
  try {
    localStorage.setItem('market.structureRange', v)
  } catch {
    /* storage blocked */
  }
})
const sdays = ref<StructureDays | null>(null)
const sError = ref('')
watch([sRange, () => props.date], async ([r, d]) => {
  if (!d) return
  sError.value = ''
  try {
    const x = await api.breadthStructure(r, d)
    if (sRange.value === r && props.date === d) sdays.value = x
  } catch (e) {
    sError.value = e instanceof Error ? e.message : String(e)
  }
}, { immediate: true })
type Cell = { text: string; cls?: string }
const num = (v: number | null, d = 2) => (v === null ? '—' : v.toFixed(d))
const signedPp = (v: number | null) => (v === null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}pp`)
const tone = (v: number | null) => (v === null || v === 0 ? '' : v > 0 ? 'up' : 'down')
const S_ROWS: { label: string; cell: (d: StructureDay) => Cell | Cell[] }[] = [
  { label: '涨/跌/平', cell: (d) => [{ text: `${d.up ?? '—'}`, cls: 'up' }, { text: '/' }, { text: `${d.down ?? '—'}`, cls: 'down' }, { text: `/${d.flat ?? '—'}` }] },
  { label: '涨停/跌停', cell: (d) => [{ text: `${d.limit_up ?? '—'}`, cls: 'up' }, { text: '/' }, { text: `${d.limit_down ?? '—'}`, cls: 'down' }] },
  { label: 'ADL', cell: (d) => ({ text: d.adl_day === null ? '—' : `${d.adl_day > 0 ? '+' : ''}${d.adl_day}`, cls: tone(d.adl_day) }) },
  { label: '涨家占比', cell: (d) => ({ text: d.up_pct === null ? '—' : `${d.up_pct.toFixed(2)}%` }) },
  { label: '涨额占比', cell: (d) => ({ text: d.up_amt_pct === null ? '—' : `${d.up_amt_pct.toFixed(2)}%` }) },
  { label: '额价差', cell: (d) => ({ text: signedPp(d.amt_gap), cls: tone(d.amt_gap) }) },
  { label: '量价差', cell: (d) => ({ text: signedPp(d.vol_gap), cls: tone(d.vol_gap) }) },
  { label: 'MCL', cell: (d) => ({ text: num(d.mcl, 1), cls: tone(d.mcl) }) },
  { label: 'TRIN_额', cell: (d) => ({ text: num(d.trin_amt), cls: d.trin_amt === null ? '' : d.trin_amt < 1 ? 'up' : 'down' }) },
  { label: 'TRIN_量', cell: (d) => ({ text: num(d.trin_vol), cls: d.trin_vol === null ? '' : d.trin_vol < 1 ? 'up' : 'down' }) },
  { label: '全A成交额', cell: (d) => ({ text: d.amount === null ? '—' : d.amount >= 1e12 ? `${(d.amount / 1e12).toFixed(2)}万亿` : `${(d.amount / 1e8).toFixed(0)}亿` }) },
  { label: '结论', cell: (d) => ({ text: d.structure_label ?? '—', cls: 'verdict-cell' }) },
]
const cells = (c: Cell | Cell[]) => (Array.isArray(c) ? c : [c])
// The structures placed along one market cycle, as a sine: the rising leg positive, the falling
// leg negative, the two turns at 0 —
//   恐慌普跌 0 (the trough's turn) → 普涨反弹 +3 → 分化·均衡 +5 → 分化·资金集中 +4 → 普涨 +2 →
//   虚涨 0 (the peak's turn) → 分化·资金流出 −3 → 少数股抱团 −5 → 抱团瓦解 −4 → 无差别下跌 −2 → 恐慌普跌.
// Every structure is drawn as a labelled level, whether or not it happened in the span.
const CYCLE: [string, number][] = [
  ['panic', 0], ['broad_up_rebound', 3], ['mixed', 5], ['mixed_cluster', 4], ['broad_up_strong', 2],
  ['fake_up', 0], ['mixed_out', -3], ['cluster_hold', -5], ['cluster_break', -4], ['broad_down', -2],
]
const LEVELS: Record<string, number> = Object.fromEntries(CYCLE)
const labelOf = (key: string) => data.value?.structure.rows.find((r) => r.key === key)?.label ?? key
// The levels to draw: one line a value, the structures sharing it (the two turns at 0) named together.
const levelLines = computed(() => {
  const byValue = new Map<number, string[]>()
  for (const [key, v] of CYCLE) byValue.set(v, [...(byValue.get(v) || []), labelOf(key)])
  // No title inside the chart (it would cover the line): the axis label says it (``levelText``).
  return [...byValue.entries()].map(([value]) => ({
    value, title: '',
    color: value > 0 ? '#f3b4b4' : value < 0 ? '#a7d8bb' : '#c0c6cf',
  }))
})
// The axis and the legend: the structure's name, then its value (分化·均衡 +5); between levels nothing.
const levelText = (v: number) => {
  const r = Math.round(v)
  const names = CYCLE.filter(([, x]) => x === r).map(([k]) => labelOf(k))
  return Math.abs(v - r) < 0.01 && names.length ? `${names.join(' / ')} ${r > 0 ? '+' : ''}${r}` : ''
}
const structureLines = computed<Line[]>(() => {
  const ds = [...(sdays.value?.days || [])].reverse().filter((d) => d.structure && d.structure in LEVELS)
  return [{ name: '市场结构', color: '#b45309', points: ds.map((d) => ({ time: d.date, value: LEVELS[d.structure!] })) }]
})

// ---- 历史研判: the reading on each day of a span, and what followed ----
const HIST_RANGES: { value: StatsRange; label: string }[] = [{ value: '60d', label: '近60天' }, { value: '6m', label: '半年' }, { value: '1y', label: '一年' }]
const histRange = rangeRef('market.verdictHistRange')
if (histRange.value === '1d') histRange.value = '6m'
const hist = ref<VerdictHistory | null>(null)
const histError = ref('')
const histLoading = ref(false)
watch([histRange, () => props.date], async ([r, d]) => {
  if (!d) return
  histLoading.value = true
  histError.value = ''
  try {
    const h = await api.breadthVerdictHistory(r, d)
    if (histRange.value === r && props.date === d) hist.value = h
  } catch (e) {
    histError.value = e instanceof Error ? e.message : String(e)
  } finally {
    histLoading.value = false
  }
}, { immediate: true })
const UP = '#e5484d'
const DOWN = '#1f9d55'
const indexLines = computed<Line[]>(() => [{ name: '中证全指', color: '#2563eb',
  points: (hist.value?.days || []).flatMap((d) => (d.close === null ? [] : [{ time: d.date, value: d.close }])) }])
const scoreLines = computed<Line[]>(() => {
  const ds = hist.value?.days || []
  return [
    { name: '短期得分', color: UP, bars: true, points: ds.map((d) => ({ time: d.date, value: d.short, color: d.short >= 0 ? UP : DOWN })) },
    { name: '中期得分', color: '#7c3aed', points: ds.map((d) => ({ time: d.date, value: d.mid })) },
  ]
})
// Right: 偏多 then up, 偏空 then down; 中性 is no call.
function hit(word: string, f: number | null): string {
  if (f === null) return '待定'
  if (word.includes('偏多')) return f > 0 ? '✓' : '✗'
  if (word.includes('偏空')) return f < 0 ? '✓' : '✗'
  return '—'
}
const rowsDesc = computed<VerdictDay[]>(() => [...(hist.value?.days || [])].reverse())
const sg = (v: number | null) => (v === null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)

// The step cell spans its rows, as in 指标说明's table.
const rows = computed(() => (data.value?.rows || []).map((r, i, all) => ({
  ...r, span: i === 0 || all[i - 1].step !== r.step ? all.filter((x) => x.step === r.step).length : 0,
})))
const STEP_NOTE: Record<string, string> = { 定趋势: '① 市场内部在变好还是变坏', 找时机: '② 有没有出现转折', 验真伪: '③ 涨跌有没有真实支撑' }
const leanClass = (l: string) => (l.includes('偏多') ? 'bull' : l.includes('偏空') ? 'bear' : 'flat')
const pp = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—' : `${v.toFixed(d)}%`)
const sp = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)
</script>

<template>
  <section class="card wide">
    <div class="head">
      <h3>市场广度综合研判</h3>
      <span class="muted small">{{ data?.date || date }}</span>
    </div>
    <p v-if="error" class="bad small">{{ error }}</p>
    <p v-else-if="loading && !data" class="muted small"><i class="pi pi-spin pi-spinner" /> 研判中</p>
    <template v-if="data">
      <!-- The conclusion first -->
      <div class="verdict">
        <div class="big">
          <div><span class="muted small">短期（后 5 日）</span><b :class="leanClass(data.conclusion.short_word)">{{ data.conclusion.short_word }}</b></div>
          <div><span class="muted small">中期（后 20 日）</span><b :class="leanClass(data.conclusion.mid_word)">{{ data.conclusion.mid_word }}</b></div>
        </div>
        <div class="why">
          <p class="summary">{{ data.conclusion.headline }}</p>
          <div v-for="p in data.conclusion.points" :key="p" class="point">{{ p }}</div>
          <ol class="steps">
            <li><b>定趋势</b>：{{ data.steps.trend.text }}</li>
            <li><b>找时机</b>：{{ data.steps.timing.text }}</li>
            <li><b>验真伪</b>：{{ data.steps.check.text }}</li>
          </ol>
          <p class="muted small">三步同类组合（腾落线方向 × MCL 正负 × 指数与腾落线关系）历史 {{ data.conclusion.joint.days }} 天：
            后 5 日上涨概率 {{ pp(data.conclusion.joint.up5) }}、后 20 日 {{ pp(data.conclusion.joint.up20) }}（基准 {{ pp(data.baseline.up5) }} / {{ pp(data.baseline.up20) }}）。</p>
        </div>
      </div>

      <!-- Each indicator -->
      <table class="vtable">
        <thead><tr><th>步骤</th><th>指标</th><th>当前读数</th><th>原因</th><th>结论</th></tr></thead>
        <tbody>
          <tr v-for="r in rows" :key="r.name">
            <td v-if="r.span" :rowspan="r.span" class="step"><b>{{ r.step }}</b><div class="muted small">{{ STEP_NOTE[r.step] }}</div></td>
            <td class="name">{{ r.name }}</td>
            <td class="reading">{{ r.reading }}</td>
            <td class="reason">{{ r.reason }}</td>
            <td class="lean"><span class="tag" :class="leanClass(r.lean)">{{ r.lean }}</span></td>
          </tr>
        </tbody>
      </table>

      <!-- 当日市场结构 -->
      <div class="struct">
        <div class="muted small">当日市场结构：腾落线（ADL）× TRIN_额 / TRIN_量 × MCL 组合判断普涨、抱团还是无差别下跌</div>
        <div class="shead">
          <SelectButton v-model="sRange" :options="S_RANGES" option-label="label" option-value="value" :allow-empty="false" size="small" />
          <span class="muted small">表格可左右滑动，「项目」列固定；最新一天在最左</span>
        </div>
        <p v-if="sError" class="bad small">{{ sError }}</p>
        <div v-if="sdays" class="dwrap">
          <table class="dtable">
            <thead><tr><th class="item">项目</th><th v-for="d in sdays.days" :key="d.date">{{ d.date }}</th></tr></thead>
            <tbody>
              <tr v-for="row in S_ROWS" :key="row.label" :class="{ last: row.label === '结论' }">
                <th class="item">{{ row.label }}</th>
                <td v-for="d in sdays.days" :key="d.date" :class="{ hit: row.label === '结论' && d.structure === data.structure.state && d.date === data.date }">
                  <span v-for="(c, i) in cells(row.cell(d))" :key="i" :class="c.cls">{{ c.text }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="sdays && sdays.days.length > 1" class="schart">
          <div class="muted small">结论走势：按一轮周期排列，上升段（恐慌普跌之后）为正、下降段（虚涨之后）为负，两个转折点为 0；每种结论都画有参考线，未出现的也标出</div>
          <LineChart :lines="structureLines" :format="levelText" :height="300" :levels="levelLines" :range="[-5.6, 5.6]" markers />
        </div>
        <table class="stable">
          <thead><tr><th>市场结构</th><th>判断条件</th><th>含义</th><th class="nr">历史天数</th><th class="nr">后 5 日上涨概率</th><th class="nr">后 20 日上涨概率</th><th class="nr">后 20 日平均</th></tr></thead>
          <tbody>
            <tr v-for="r in data.structure.rows" :key="r.key" :class="{ on: r.today }">
              <td class="name">{{ r.label }}<span v-if="r.today" class="now">今日</span></td>
              <td class="rule">{{ r.rule }}</td>
              <td class="meaning">{{ r.meaning }}</td>
              <td class="nr">{{ r.days }}</td>
              <td class="nr" :class="r.days >= 10 && (r.up5 ?? 0) >= data.baseline.up5! + 5 ? 'up' : r.days >= 10 && (r.up5 ?? 100) <= data.baseline.up5! - 5 ? 'down' : ''">{{ r.days ? pp(r.up5) : '—' }}</td>
              <td class="nr" :class="r.days >= 10 && (r.up20 ?? 0) >= data.baseline.up20! + 5 ? 'up' : r.days >= 10 && (r.up20 ?? 100) <= data.baseline.up20! - 5 ? 'down' : ''">{{ r.days ? pp(r.up20) : '—' }}</td>
              <td class="nr">{{ r.days ? sp(r.avg20) : '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p class="muted small">ADL 以当日涨家占比衡量（≥ 60% 普涨、≤ 40% 普跌），资金以 TRIN_额 衡量（&lt; 0.8 集中在上涨股、&gt; 1.2 集中在下跌股），
          TRIN_量 作为印证；普跌中 TRIN_额 从前 3 日低点回升 0.2 以上、进入 0.8–1.2，即「抱团瓦解」，正走向无差别下跌；MCL 区分健康普涨与超跌反弹。
          上涨概率与基准（{{ pp(data.baseline.up5) }} / {{ pp(data.baseline.up20) }}）相差 5 个百分点以上标红 / 绿；天数少于 10 天的仅供参考。</p>
      </div>

      <!-- What would turn it -->
      <div class="watch">
        <div class="muted small">下一步观察：出现以下信号时，历史上的后市表现</div>
        <table class="wtable">
          <thead><tr><th>信号</th><th class="nr">历史天数</th><th class="nr">后 5 日上涨概率</th><th class="nr">平均</th><th class="nr">后 20 日上涨概率</th><th class="nr">平均</th></tr></thead>
          <tbody>
            <tr v-for="w in data.conclusion.watch" :key="w.signal">
              <td>{{ w.signal }}</td><td class="nr">{{ w.days }}</td>
              <td class="nr" :class="(w.up5 ?? 0) >= data.baseline.up5! + 5 ? 'up' : ''">{{ pp(w.up5) }}</td><td class="nr">{{ sp(w.avg5) }}</td>
              <td class="nr" :class="(w.up20 ?? 0) >= data.baseline.up20! + 5 ? 'up' : ''">{{ pp(w.up20) }}</td><td class="nr">{{ sp(w.avg20) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <!-- 历史研判 -->
      <div class="hist">
        <div class="head">
          <h4>历史研判<span class="muted small">每天按当天已知的数据给出的结论，以及之后的实际涨跌</span></h4>
          <Select v-model="histRange" :options="HIST_RANGES" option-label="label" option-value="value" size="small" class="range" />
        </div>
        <p v-if="histError" class="bad small">{{ histError }}</p>
        <p v-else-if="histLoading && !hist" class="muted small"><i class="pi pi-spin pi-spinner" /> 逐日回算中（约数秒）</p>
        <template v-if="hist">
          <div class="acc">
            <div v-for="(a, k) in { 短期: hist.accuracy.short, 中期: hist.accuracy.mid }" :key="k">
              <div class="muted small">{{ k }}判断命中率（{{ k === '短期' ? '后 5 日' : '后 20 日' }}）</div>
              <div><span class="up">偏多</span> {{ a.bull.days }} 天，命中 <b>{{ a.bull.rate === null ? '—' : a.bull.rate + '%' }}</b>
                <span class="muted small">（随机上涨率 {{ a.all_up ?? '—' }}%）</span></div>
              <div><span class="down">偏空</span> {{ a.bear.days }} 天，命中 <b>{{ a.bear.rate === null ? '—' : a.bear.rate + '%' }}</b>
                <span class="muted small">（随机下跌率 {{ a.all_up === null ? '—' : (100 - a.all_up).toFixed(1) }}%）</span></div>
            </div>
          </div>
          <LineChart :lines="indexLines" :format="(v) => v.toFixed(0)" :height="150" />
          <LineChart :lines="scoreLines" :format="(v) => v.toFixed(1)" :height="130" />
          <div class="hwrap">
            <table class="htable">
              <thead><tr><th>日期</th><th>短期</th><th>中期</th><th class="nr">①定趋势</th><th class="nr">②找时机</th><th class="nr">③验真伪</th>
                <th class="nr">后 5 日</th><th>短期命中</th><th class="nr">后 20 日</th><th>中期命中</th></tr></thead>
              <tbody>
                <tr v-for="d in rowsDesc" :key="d.date">
                  <td>{{ d.date }}</td>
                  <td :class="leanClass(d.short_word)">{{ d.short_word }}</td>
                  <td :class="leanClass(d.mid_word)">{{ d.mid_word }}</td>
                  <td v-for="st in (['定趋势', '找时机', '验真伪'] as const)" :key="st" class="nr" :class="d.steps[st] >= 5 ? 'up' : d.steps[st] <= -5 ? 'down' : ''">{{ d.steps[st] > 0 ? '+' : '' }}{{ d.steps[st].toFixed(1) }}</td>
                  <td class="nr" :class="d.f5 === null ? '' : d.f5 > 0 ? 'up' : 'down'">{{ sg(d.f5) }}</td>
                  <td class="ctr">{{ hit(d.short_word, d.f5) }}</td>
                  <td class="nr" :class="d.f20 === null ? '' : d.f20 > 0 ? 'up' : 'down'">{{ sg(d.f20) }}</td>
                  <td class="ctr">{{ hit(d.mid_word, d.f20) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="muted small">命中：判断偏多（含略偏多）之后中证全指上涨、偏空之后下跌记 ✓；中性不算判断（—）；结果尚未知晓记「待定」。
            各步骤得分为该步各指标「同类状态上涨概率高出基准」的平均（百分点）。每天都只用当天之前的数据判断，因此可以检验这套方法过去是否有效。</p>
        </template>
      </div>
      <p class="muted small note">每项结论都按本地历史统计：{{ data.history_from }} 至 {{ data.history_to }}（只用当日之前已知后 20 日结果的日子），
        看历史上处于同一状态的日子之后中证全指 5 日、20 日的上涨概率，与全部日子的基准（{{ pp(data.baseline.up5) }} / {{ pp(data.baseline.up20) }}）相比：
        两者都高出 5 个百分点为「偏多」，都低 5 个百分点为「偏空」，只有 5 日的为「短期偏多 / 偏空」。综合时「验真伪」权重最高（历史上最可靠）。
        样本仅约两年、市场环境会变，这是历史统计，<b>不是预测</b>；中证全指数据截至 {{ data.index_date }}。</p>
    </template>
  </section>
</template>

<style scoped>
.wide { grid-column: 1 / -1; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h3 { margin: 0; font-size: 15px; }
.small { font-size: 12px; }
.bad { color: var(--up); }
.verdict { display: grid; grid-template-columns: 220px 1fr; gap: 20px; margin: 10px 0 12px; padding: 12px; border-radius: 8px; background: #fafbfc; border: 1px solid var(--border); }
.big { display: flex; flex-direction: column; gap: 10px; justify-content: center; }
.big > div { display: flex; flex-direction: column; }
.big b { font-size: 24px; }
.summary { margin: 0 0 6px; font-size: 14px; font-weight: 600; line-height: 1.6; }
.point { font-size: 13px; font-weight: 600; line-height: 1.7; }
.point:last-of-type { margin-bottom: 8px; }
.steps { margin: 0 0 6px; padding-left: 20px; font-size: 13px; line-height: 1.7; }
.bull { color: var(--up); }
.bear { color: var(--down); }
.flat { color: #b45309; }
.vtable, .wtable { width: 100%; border-collapse: collapse; font-size: 12.5px; line-height: 1.6; }
.vtable th, .vtable td, .wtable th, .wtable td { border: 1px solid var(--border); padding: 6px 8px; vertical-align: middle; text-align: left; }
.vtable th, .wtable th { background: #f6f7f9; font-weight: 600; white-space: nowrap; }
.step { text-align: center !important; background: #fafbfc; white-space: nowrap; }
.name { font-weight: 600; white-space: nowrap; }
.reading { white-space: nowrap; font-variant-numeric: tabular-nums; }
.lean { text-align: center !important; white-space: nowrap; }
.tag { font-size: 12px; font-weight: 600; padding: 1px 8px; border-radius: 10px; background: #f1f3f6; }
.tag.bull { background: #fdecec; }
.tag.bear { background: #e8f5ee; }
.tag.flat { background: #fff4e5; }
.watch { margin-top: 12px; }
.struct { margin-top: 12px; }
.today { margin: 4px 0 6px; font-size: 13px; line-height: 1.7; font-variant-numeric: tabular-nums; }
.today .lbl { color: #111827; font-weight: 700; }
.today .state { color: #b45309; font-size: 14px; }
.shead { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 6px 0; }
.dwrap { overflow-x: auto; max-width: 100%; border: 1px solid var(--border); border-radius: 6px; margin-bottom: 8px; }
.dtable { border-collapse: separate; border-spacing: 0; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.dtable th, .dtable td { padding: 5px 12px; border-bottom: 1px solid #f1f3f6; border-right: 1px solid #f1f3f6; text-align: right; }
.dtable thead th { background: #f6f7f9; font-weight: 600; }
.dtable .item { position: sticky; left: 0; z-index: 2; background: #fafbfc; text-align: left; font-weight: 700; color: #111827;
                box-shadow: inset -1px 0 0 var(--border); }
.dtable thead .item { z-index: 3; background: #f6f7f9; }
.dtable tr.last td { font-weight: 600; }
.dtable .verdict-cell { color: #b45309; }
.dtable td.hit { background: #fff7e6; }
.schart { margin: 4px 0 10px; }
.stable { width: 100%; border-collapse: collapse; font-size: 12.5px; line-height: 1.55; margin-top: 4px; }
.stable th, .stable td { border: 1px solid var(--border); padding: 5px 8px; vertical-align: middle; text-align: left; }
.stable th { background: #f6f7f9; font-weight: 600; white-space: nowrap; }
.stable .name { font-weight: 600; white-space: nowrap; }
.stable .rule { white-space: nowrap; color: #374151; }
.stable tr.on td { background: #fff7e6; }
.now { margin-left: 6px; font-size: 11px; padding: 0 6px; border-radius: 8px; background: #b45309; color: #fff; font-weight: 500; }
.wtable { margin-top: 4px; }
.nr { text-align: right !important; font-variant-numeric: tabular-nums; }
.note { margin: 10px 0 0; line-height: 1.6; }
.hist { margin-top: 16px; padding-top: 10px; border-top: 1px dashed var(--border); }
.hist h4 { margin: 0; font-size: 14px; display: flex; align-items: baseline; gap: 10px; }
.range { width: 110px; }
.acc { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 8px 0; font-size: 13px; line-height: 1.7; font-variant-numeric: tabular-nums; }
.hwrap { max-height: 320px; overflow-y: auto; margin-top: 8px; }
.htable { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
.htable th { position: sticky; top: 0; background: #f6f7f9; font-weight: 600; text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--border); white-space: nowrap; }
.htable td { padding: 3px 6px; border-bottom: 1px solid #f1f3f6; white-space: nowrap; }
.ctr { text-align: center; }
.up { color: var(--up); }
.down { color: var(--down); }
@media (max-width: 900px) { .acc { grid-template-columns: 1fr; } }
@media (max-width: 900px) { .verdict { grid-template-columns: 1fr; } }
</style>
