<script setup lang="ts">
// 宽基ETF → 个股: what the day's share changes come to in each stock — each fund's change × its
// close × its index's weight, summed over the funds a stock is in, with each fund's part. It follows
// the day shown above (hovered or the last), asked for a moment after the mouse settles.
import { computed, ref, watch } from 'vue'
import { api, type EtfStocks } from '../api'

const props = defineProps<{ date: string | null }>()
const SHOW = 20

const cache = new Map<string, EtfStocks>()
const data = ref<EtfStocks | null>(null)
const error = ref('')
const loading = ref(false)
const all = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
watch(() => props.date, (d) => {
  clearTimeout(timer)
  if (!d) return
  const hit = cache.get(d)
  if (hit) {
    data.value = hit
    return
  }
  timer = setTimeout(async () => {
    loading.value = true
    error.value = ''
    try {
      const r = await api.etfStocks(d)
      cache.set(d, r)
      if (props.date === d) data.value = r
    } catch (e) {
      if (props.date === d) error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }, 250)
}, { immediate: true })

const names = computed(() => new Map((data.value?.funds || []).map((f) => [f.code, f.name])))
// A stock's share of the day's total (%); none on a day whose total is about nil.
const ratio = (v: number) => (data.value && Math.abs(data.value.total) >= 0.01 ? (v / data.value.total) * 100 : null)
const topSum = computed(() => (data.value?.stocks || []).reduce((a, s) => a + s.amount, 0))
// Sorting by 合计 or 比率: largest first, then smallest first, then back to the size of the amount
// (the default, either way). Over all the stocks sent, before the first SHOW are cut.
type SortKey = 'amount' | 'ratio'
const sortKey = ref<SortKey | null>(null)
const sortDir = ref(-1)
function sortBy(k: SortKey) {
  if (sortKey.value !== k) {
    sortKey.value = k
    sortDir.value = -1
  } else if (sortDir.value < 0) sortDir.value = 1
  else sortKey.value = null
}
const rows = computed(() => {
  const all_ = [...(data.value?.stocks || [])]
  const k = sortKey.value
  if (k) {
    const val = (x: { amount: number }) => (k === 'amount' ? x.amount : ratio(x.amount) ?? 0)
    all_.sort((a, b) => (val(a) - val(b)) * sortDir.value)
  }
  return all_.slice(0, all.value ? undefined : SHOW)
})
const icon = (k: SortKey) => (sortKey.value !== k ? 'pi-sort-alt' : sortDir.value < 0 ? 'pi-sort-amount-down' : 'pi-sort-amount-up')
const pctText = (v: number | null) => (v === null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)
const weightsDates = computed(() => [...new Set((data.value?.funds || []).map((f) => f.weights_date))].join('、'))
const cls = (v: number) => (v > 0 ? 'up' : v < 0 ? 'down' : 'muted')
// 亿 to two places, or 万 when under 1亿.
const money = (v: number) => {
  const s = v > 0 ? '+' : v < 0 ? '−' : ''
  const a = Math.abs(v)
  return a >= 1 ? `${s}${a.toFixed(2)}亿` : `${s}${(a * 1e4).toFixed(0)}万`
}
</script>

<template>
  <div class="stocks">
    <h4>相当于买卖了哪些个股
      <span class="muted small">每只 ETF 的份额变化 × 收盘价 × 指数成分股权重，同一只股票跨 ETF 合计（亿元）</span></h4>
    <p v-if="error" class="bad small">{{ error }}</p>
    <template v-else-if="data">
      <p class="small sum">
        {{ data.date }}：20 只 ETF 份额变化折合 <b :class="cls(data.total)">{{ money(data.total) }}元</b>，
        相当于按权重{{ data.total >= 0 ? '买入' : '卖出' }}了 {{ data.count }} 只成分股，下表为金额最大的
        {{ data.stocks.length }} 只，合计 <b :class="cls(topSum)">{{ money(topSum) }}元</b>，占
        <b :class="cls(topSum)">{{ pctText(ratio(topSum)) }}</b><span v-if="loading" class="muted">（更新中）</span>。
        <span class="muted">按 ETF：</span>
        <span v-for="f in data.funds.filter((x) => x.amount)" :key="f.code" class="fund">{{ f.name }}
          <b :class="cls(f.amount)">{{ money(f.amount) }}</b></span>
      </p>
      <table class="tbl">
        <thead><tr><th>#</th><th>股票</th>
          <th class="r sort" :class="{ on: sortKey === 'amount' }" @click="sortBy('amount')">合计<i class="pi" :class="icon('amount')" /></th>
          <th class="r sort" :class="{ on: sortKey === 'ratio' }" title="合计 ÷ 20 只 ETF 份额变化折合" @click="sortBy('ratio')">比率<i class="pi" :class="icon('ratio')" /></th>
          <th>来自哪只 ETF</th></tr></thead>
        <tbody>
          <tr v-for="(s, i) in rows" :key="s.code">
            <td class="muted">{{ i + 1 }}</td>
            <td class="nm"><RouterLink :to="`/stock/${s.code}`" class="link">{{ s.name }}</RouterLink>
              <span class="muted code">{{ s.code }}</span></td>
            <td class="r"><b :class="cls(s.amount)">{{ money(s.amount) }}</b></td>
            <td class="r" :class="cls(s.amount)">{{ pctText(ratio(s.amount)) }}</td>
            <td class="parts">
              <span v-for="[f, a] in s.parts" :key="f">{{ names.get(f) || f }} <span :class="cls(a)">{{ money(a) }}</span></span>
            </td>
          </tr>
        </tbody>
      </table>
      <button v-if="data.stocks.length > SHOW" class="more" @click="all = !all">
        {{ all ? `收起，只看前 ${SHOW} 只` : `显示全部 ${data.stocks.length} 只` }}</button>
      <p class="muted small note">
        ETF 多为实物申购：申购方按指数权重交给基金一篮子股票，换得新份额，赎回相反。所以这里是这笔资金按权重折合到个股的金额，
        是新增买入的<b>上限</b>：当天在市场上买入股票再申购的是新资金，用已持有的股票换成 ETF 的不是。
        权重取中证指数 / 国证指数每月公布的成分股权重（{{ weightsDates }}），跨月有偏差。
        <span v-if="data.note" class="bad">{{ data.note }}</span>
      </p>
    </template>
    <p v-else-if="loading" class="muted small"><i class="pi pi-spin pi-spinner" /> 计算中</p>
  </div>
</template>

<style scoped>
.stocks { margin-top: 14px; border-top: 1px solid #eef1f4; padding-top: 10px; }
.stocks:first-child { margin-top: 0; border-top: 0; padding-top: 0; }
h4 { margin: 0 0 6px; font-size: 14px; }
.small { font-size: 12px; }
.sum { margin: 4px 0 8px; line-height: 1.7; }
.fund { margin-right: 10px; white-space: nowrap; }
.tbl { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
.tbl th { text-align: left; font-weight: 500; color: var(--p-text-muted-color, #6b7785); padding: 4px 6px; border-bottom: 1px solid #e3e7ec; }
.tbl td { padding: 4px 6px; border-bottom: 1px solid #f1f3f6; vertical-align: top; }
.r { text-align: right; white-space: nowrap; }
.sort { cursor: pointer; user-select: none; }
.sort.on { color: var(--p-text-color, #1f2933); }
.sort i { font-size: 10px; margin-left: 3px; }
.nm { white-space: nowrap; }
.code { margin-left: 4px; font-size: 11px; }
.parts { line-height: 1.6; }
.parts > span { margin-right: 12px; white-space: nowrap; }
.link { color: inherit; text-decoration: none; }
.link:hover { color: var(--p-primary-color, #2563eb); }
.more { margin-top: 6px; border: 0; background: none; color: var(--p-primary-color, #2563eb); cursor: pointer; font-size: 12px; padding: 0; }
.note { margin: 8px 0 0; line-height: 1.6; }
.bad { color: var(--up); }
</style>
