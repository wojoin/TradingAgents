<script setup lang="ts">
// The day's Shenwan industries ranked: average and median change of their stocks, the share
// that rose, the amount traded and its share of the market, and the best stock of each.
import { computed, ref } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import SelectButton from 'primevue/selectbutton'
import { formatPct, formatYuan, upDownClass, type MarketRow } from '../api'

const props = defineProps<{ rows: MarketRow[] }>()
const emit = defineEmits<{ pick: [industry: string] }>()

const level = ref<'sw1' | 'sw2'>('sw1')
const LEVELS = [{ value: 'sw1', label: '一级行业' }, { value: 'sw2', label: '二级行业' }]

const median = (xs: number[]) => {
  if (!xs.length) return null
  const s = [...xs].sort((a, b) => a - b)
  const m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

const sectors = computed(() => {
  const groups = new Map<string, MarketRow[]>()
  for (const r of props.rows) {
    // A level-2 industry carries its level-1 one: 食品饮料-白酒Ⅱ.
    const key = level.value === 'sw1' ? r.industry
      : r.sub_industry && (r.industry ? `${r.industry}-${r.sub_industry}` : r.sub_industry)
    if (!key) continue
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(r)
  }
  const market = props.rows.reduce((a, r) => a + (r.amount || 0), 0)
  return [...groups.entries()].map(([name, rs]) => {
    const pcts = rs.map((r) => r.pct_chg).filter((p): p is number => typeof p === 'number')
    const p5 = rs.map((r) => r.pct_5d).filter((p): p is number => typeof p === 'number')
    const amount = rs.reduce((a, r) => a + (r.amount || 0), 0)
    const best = rs.reduce<MarketRow | null>((a, r) => ((r.pct_chg ?? -Infinity) > (a?.pct_chg ?? -Infinity) ? r : a), null)
    return {
      name, count: rs.length,
      avg: pcts.length ? pcts.reduce((a, p) => a + p, 0) / pcts.length : null,
      median: median(pcts),
      avg5d: p5.length ? p5.reduce((a, p) => a + p, 0) / p5.length : null,   // equal-weight, like 平均涨幅
      upShare: pcts.length ? (pcts.filter((p) => p > 0).length / pcts.length) * 100 : null,
      amount, amountShare: market ? (amount / market) * 100 : null,
      bestName: best?.name ?? null,
      bestPct: best?.pct_chg ?? null,         // 领涨 sorts by the leader's change
    }
  })
})

function pick(name: string) {
  if (level.value === 'sw1') emit('pick', name)
}
</script>

<template>
  <section class="card">
    <div class="head">
      <h3>行业涨跌榜</h3>
      <SelectButton v-model="level" :options="LEVELS" option-label="label" option-value="value" :allow-empty="false" size="small" />
    </div>
    <p class="muted small sub">申万{{ level === 'sw1' ? '一' : '二' }}级 {{ sectors.length }} 个行业 · 平均为等权平均{{ level === 'sw1' ? ' · 点行业名筛选上方表格' : '' }}</p>
    <DataTable :value="sectors" data-key="name" sort-field="avg" :sort-order="-1" scrollable scroll-height="320px"
               size="small" striped-rows removable-sort class="ind">
      <Column field="name" header="行业" sortable :style="{ minWidth: level === 'sw1' ? '96px' : '170px' }">
        <template #body="{ data }">
          <a v-if="level === 'sw1'" class="link" @click="pick(data.name)">{{ data.name }}</a>
          <span v-else>{{ data.name }}</span>
        </template>
      </Column>
      <Column field="avg" header="平均涨幅" sortable header-class="nr" body-class="nr">
        <template #body="{ data }"><span :class="upDownClass(data.avg)">{{ formatPct(data.avg) }}</span></template>
      </Column>
      <Column field="median" header="中位涨幅" sortable header-class="nr" body-class="nr">
        <template #body="{ data }"><span :class="upDownClass(data.median)">{{ formatPct(data.median) }}</span></template>
      </Column>
      <Column field="avg5d" header="5日涨幅" sortable header-class="nr" body-class="nr">
        <template #body="{ data }"><span :class="upDownClass(data.avg5d)">{{ formatPct(data.avg5d) }}</span></template>
      </Column>
      <Column field="upShare" header="上涨占比" sortable header-class="nr" body-class="nr">
        <template #body="{ data }">{{ data.upShare === null ? '—' : `${data.upShare.toFixed(0)}%` }}</template>
      </Column>
      <Column field="amount" header="成交额" sortable header-class="nr" body-class="nr">
        <template #body="{ data }">{{ formatYuan(data.amount) }}</template>
      </Column>
      <Column field="amountShare" header="成交占比" sortable header-class="nr" body-class="nr">
        <template #body="{ data }">{{ data.amountShare === null ? '—' : `${data.amountShare.toFixed(1)}%` }}</template>
      </Column>
      <Column field="count" header="家数" sortable header-class="nr" body-class="nr" />
      <Column field="bestPct" header="领涨" sortable style="min-width: 120px">
        <template #body="{ data }">
          <template v-if="data.bestName">{{ data.bestName }}
            <span :class="data.bestPct > 0 ? 'up' : data.bestPct === 0 ? 'flat' : 'down'">{{ formatPct(data.bestPct) }}</span>
          </template>
          <span v-else>—</span>
        </template>
      </Column>
    </DataTable>
  </section>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h3 { margin: 0; font-size: 15px; }
.small { font-size: 12px; }
.sub { margin: 6px 0; }
.link { cursor: pointer; }
.flat { color: var(--muted); }
.link:hover { color: var(--up); }
:deep(.ind th.nr), :deep(.ind td.nr) { text-align: right; font-variant-numeric: tabular-nums; }
:deep(.ind th.nr .p-datatable-column-header-content) { justify-content: flex-end; }
:deep(.ind td) { white-space: nowrap; }
</style>
