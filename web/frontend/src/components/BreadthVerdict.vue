<script setup lang="ts">
// 市场广度综合研判: the breadth indicators read in three steps (定趋势 → 找时机 → 验真伪), each
// state judged by how the market did after the same state in the past, and the conclusion built
// up from them. A summary of history, not a forecast.
import { computed, ref, watch } from 'vue'
import Select from 'primevue/select'
import { api, type BreadthVerdict, type StatsRange, type VerdictDay, type VerdictHistory } from '../api'
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
