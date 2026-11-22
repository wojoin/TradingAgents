<script setup lang="ts">
// One fund's constituents (its index's latest weights) with each stock's latest quote, TTM P/E,
// ROE and market value. All of them come at once (at most 中证1000's 1000); 50 are shown, 100 more
// a click, or all — so sorting a column sorts every constituent, not just the ones shown.
import { computed, ref, watch } from 'vue'
import { api, type EtfHoldingRow, type EtfHoldings } from '../api'

const props = defineProps<{ code: string }>()
const FIRST = 50
const MORE = 100

const cache = new Map<string, EtfHoldings>()   // per page view: a fund opened again is not asked for again
const data = ref<EtfHoldings | null>(null)
const error = ref('')
const shown = ref(FIRST)
watch(() => props.code, async (c) => {
  shown.value = FIRST
  error.value = ''
  data.value = cache.get(c) ?? null
  if (data.value) return
  try {
    const r = await api.etfHoldings(c)
    cache.set(c, r)
    if (props.code === c) data.value = r
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}, { immediate: true })

type Key = keyof EtfHoldingRow
const COLS: { key: Key; label: string; left?: boolean }[] = [
  { key: 'weight', label: '持仓占比' }, { key: 'price', label: '最新' }, { key: 'pct_chg', label: '涨幅' },
  { key: 'turnover', label: '换手率' }, { key: 'amount', label: '成交额' }, { key: 'industry', label: '行业', left: true }, { key: 'pe_ttm', label: '市盈率(TTM)' },
  { key: 'roe', label: 'ROE' }, { key: 'total_mv', label: '总市值' },
]
const sortKey = ref<Key>('weight')
const sortDir = ref(-1)
function sortBy(k: Key) {
  if (sortKey.value === k) sortDir.value = -sortDir.value
  else {
    sortKey.value = k
    sortDir.value = k === 'industry' ? 1 : -1      // text A→Z first, numbers largest first
  }
}
// Sorted over every constituent; a missing value goes last either way. Text (the industry) by its
// pinyin, so one industry's stocks come together.
const sorted = computed(() => {
  const rows = [...(data.value?.rows || [])]
  const k = sortKey.value
  return rows.sort((a, b) => {
    const x = a[k]
    const y = b[k]
    if (x === null || y === null) return x === null ? (y === null ? 0 : 1) : -1
    const c = typeof x === 'string' ? x.localeCompare(y as string, 'zh-CN') : (x as number) - (y as number)
    return c * sortDir.value
  })
})
const rows = computed(() => sorted.value.slice(0, shown.value))
const left = computed(() => (data.value?.count ?? 0) - rows.value.length)

const num = (v: number | null, d = 2) => (v === null ? '—' : v.toFixed(d))
const pct = (v: number | null) => (v === null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)
const yi = (v: number | null) => (v === null ? '—' : v >= 1e12 ? `${(v / 1e12).toFixed(2)}万亿` : `${(v / 1e8).toFixed(2)}亿`)
const cls = (v: number | null) => (!v ? '' : v > 0 ? 'up' : 'down')
</script>

<template>
  <div class="hold">
    <p v-if="error" class="bad small">{{ error }}</p>
    <p v-else-if="!data" class="muted small"><i class="pi pi-spin pi-spinner" /> 读取成分股</p>
    <template v-else>
      <p class="small muted head">{{ data.name }} 跟踪 <b>{{ data.index_name }}</b>（{{ data.index }}），{{ data.count }} 只成分股；
        持仓占比为指数成分股权重（{{ data.weights_date }}），行情为 {{ data.date }}，ROE 为 {{ data.roe_label }}（报告期累计，未年化）。点表头排序。</p>
      <table class="tbl">
        <thead><tr>
          <th class="l">#</th><th class="l">名称 / 代码</th>
          <th v-for="c in COLS" :key="c.key" class="sort" :class="[c.left ? 'l' : 'r', { on: sortKey === c.key }]" @click="sortBy(c.key)">
            {{ c.label }}<i v-if="sortKey === c.key" class="pi" :class="sortDir < 0 ? 'pi-sort-amount-down' : 'pi-sort-amount-up'" /></th>
        </tr></thead>
        <tbody>
          <tr v-for="(r, i) in rows" :key="r.code">
            <td class="muted">{{ i + 1 }}</td>
            <td class="nm"><RouterLink :to="`/stock/${r.code}`" class="link">{{ r.name }}</RouterLink><span class="code">{{ r.code }}</span></td>
            <td class="r">{{ num(r.weight, 3) }}%</td>
            <td class="r" :class="cls(r.pct_chg)">{{ num(r.price) }}</td>
            <td class="r" :class="cls(r.pct_chg)">{{ pct(r.pct_chg) }}</td>
            <td class="r">{{ r.turnover === null ? '—' : `${r.turnover.toFixed(2)}%` }}</td>
            <td class="r">{{ yi(r.amount) }}</td>
            <td class="ind" :title="r.industry ?? ''">{{ r.industry ?? '—' }}</td>
            <td class="r">{{ r.pe_ttm === null ? '—' : r.pe_ttm < 0 ? '亏损' : r.pe_ttm.toFixed(2) }}</td>
            <td class="r" :class="{ down: r.roe !== null && r.roe < 0 }">{{ r.roe === null ? '—' : `${r.roe.toFixed(2)}%` }}</td>
            <td class="r">{{ yi(r.total_mv) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="left > 0 || shown > FIRST" class="more">
        <span class="muted small">显示 {{ rows.length }} / {{ data.count }}</span>
        <button v-if="left > 0" @click="shown += MORE">更多 {{ Math.min(MORE, left) }} 只</button>
        <button v-if="left > MORE" @click="shown = data.count">全部</button>
        <button v-if="shown > FIRST" @click="shown = FIRST">收起</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.hold { padding: 4px 8px 8px 36px; }
.head { margin: 2px 0 6px; }
.small { font-size: 12px; }
.tbl { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
.tbl th { font-weight: 500; color: var(--p-text-muted-color, #6b7785); padding: 4px 8px; border-bottom: 1px solid #e3e7ec; white-space: nowrap; }
.tbl td { padding: 3px 8px; border-bottom: 1px solid #f1f3f6; white-space: nowrap; }
.l { text-align: left; }
.r { text-align: right; }
.sort { cursor: pointer; user-select: none; }
.sort.on { color: var(--p-text-color, #1f2933); }
.sort i { font-size: 10px; margin-left: 3px; }
.ind { max-width: 260px; overflow: hidden; text-overflow: ellipsis; color: #4b5563; }
.code { margin-left: 6px; color: #9aa3ad; font-size: 11px; }
.link { color: inherit; text-decoration: none; }
.link:hover { color: var(--p-primary-color, #2563eb); }
.more { display: flex; align-items: center; gap: 12px; margin-top: 6px; }
.more button { border: 0; background: none; color: var(--p-primary-color, #2563eb); cursor: pointer; font-size: 12px; padding: 0; }
.bad { color: var(--up); }
</style>
