<script setup lang="ts">
// 主线题材: the themes of the day's limit-ups (同花顺's 涨停原因 split at "+"), with how many
// limit-ups each had on each of the last 3, 5 or 10 trading days, and today's stocks.
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import SelectButton from 'primevue/selectbutton'
import { api, type MarketThemes } from '../api'

const props = defineProps<{ date: string | null }>()
const router = useRouter()

function stored(key: string, fallback: number) {
  let v = fallback
  try {
    const s = Number(localStorage.getItem(key))
    if ([3, 5, 10].includes(s)) v = s
  } catch {
    /* storage blocked: the default */
  }
  const r = ref(v)
  watch(r, (x) => {
    try {
      localStorage.setItem(key, String(x))
    } catch {
      /* storage blocked */
    }
  })
  return r
}
const span = stored('market.themeDays', 5)
const SPANS = [{ value: 3, label: '近3日' }, { value: 5, label: '近5日' }, { value: 10, label: '近10日' }]
const data = ref<MarketThemes | null>(null)
const error = ref('')
const loading = ref(false)
watch([span, () => props.date], async ([n, d]) => {
  if (!d) return
  loading.value = true
  error.value = ''
  try {
    const t = await api.marketThemes(n, d)
    if (span.value === n && props.date === d) data.value = t
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}, { immediate: true })

const mmdd = (d: string) => d.slice(5)
// Deeper red for more limit-ups (full at 6).
function heat(n: number) {
  if (!n) return { background: '#f6f7f9', color: '#c0c6cf' }
  const a = Math.min(n / 6, 1) * 0.8 + 0.12
  return { background: `rgba(229, 72, 77, ${a.toFixed(2)})`, color: a > 0.5 ? '#fff' : '#1f2933' }
}
const missing = (d: string) => !!data.value && !data.value.have.includes(d)
</script>

<template>
  <section class="card wide">
    <div class="head">
      <h3>主线题材</h3>
      <SelectButton v-model="span" :options="SPANS" option-label="label" option-value="value" :allow-empty="false" size="small" />
    </div>
    <p class="muted small sub">把每只涨停股的涨停原因（同花顺）按「+」拆成题材，统计每天各题材的涨停家数，按当日家数排序。
      <b>连续多日都有涨停的题材是主线</b>；只出现一天的多为一日游。北交所股票没有涨停原因，不计入。</p>
    <p v-if="error" class="bad small">{{ error }}</p>
    <p v-else-if="loading && !data" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中（首次需从同花顺获取各日涨停原因）</p>
    <p v-else-if="data && !data.themes.length" class="muted small">这几天没有取到涨停原因。</p>
    <div v-if="data && data.themes.length" class="wrap">
      <table class="themes">
        <thead>
          <tr>
            <th class="nm">题材</th>
            <th v-for="d in data.dates" :key="d" :class="{ today: d === data.date }" :title="missing(d) ? '当日未取到涨停原因' : ''">
              {{ mmdd(d) }}<span v-if="missing(d)" class="muted">*</span>
            </th>
            <th class="num">合计</th>
            <th class="num">持续</th>
            <th class="st">今日涨停股</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in data.themes" :key="t.name">
            <td class="nm"><b>{{ t.name }}</b></td>
            <td v-for="(n, i) in t.counts" :key="i" class="cell" :style="heat(n)">{{ n || '·' }}</td>
            <td class="num">{{ t.total }}</td>
            <td class="num" :class="{ hot: t.days_on >= Math.min(3, data.dates.length) }">{{ t.days_on }}/{{ data.dates.length }} 天</td>
            <td class="st">
              <a v-for="s in t.stocks" :key="s.code" class="chip" :title="s.code" @click="router.push(`/stock/${s.code}`)">{{ s.name }}</a>
              <span v-if="!t.stocks.length" class="muted">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.wide { grid-column: 1 / -1; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h3 { margin: 0; font-size: 15px; }
.small { font-size: 12px; }
.sub { margin: 6px 0; }
.bad { color: var(--up); }
.wrap { overflow-x: auto; max-height: 420px; overflow-y: auto; }
.themes { border-collapse: separate; border-spacing: 2px; font-size: 12px; font-variant-numeric: tabular-nums; }
.themes th { font-weight: 500; color: var(--muted); padding: 2px 4px; white-space: nowrap; position: sticky; top: 0; background: #fff; z-index: 1; }
.themes th.today { color: var(--up); font-weight: 600; }
.themes td { padding: 3px 6px; white-space: nowrap; }
.nm { text-align: left; min-width: 96px; }
.cell { text-align: center; min-width: 34px; border-radius: 3px; }
.num { text-align: right; }
.hot { color: var(--up); font-weight: 600; }
.st { white-space: normal !important; min-width: 220px; }
.chip { display: inline-block; font-size: 12px; padding: 1px 7px; margin: 1px 4px 1px 0; border: 1px solid var(--border);
        border-radius: 10px; cursor: pointer; }
.chip:hover { border-color: var(--up); }
</style>
