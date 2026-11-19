<script setup lang="ts">
// 业绩预告: a report period's earnings forecasts announced up to the day (Eastmoney): how many of
// each type, the share that are good news, by 申万一级 industry, the biggest changes and the latest.
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import SelectButton from 'primevue/selectbutton'
import { api, upDownClass, type ForecastRow, type MarketForecasts } from '../api'

const props = defineProps<{ date: string | null }>()
const router = useRouter()
const data = ref<MarketForecasts | null>(null)
const error = ref('')
const loading = ref(false)
const period = ref<string | null>(null)        // null: the server picks the latest busy period

watch([() => props.date, period], async ([d, p]) => {
  if (!d) return
  loading.value = true
  error.value = ''
  try {
    const r = await api.marketForecasts(d, p || undefined)
    if (props.date === d && period.value === p) data.value = r
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}, { immediate: true })

// 2026-09-30 -> 2026 三季报
const periodName = (p: string) => `${p.slice(0, 4)} ${({ '03': '一季报', '06': '中报', '09': '三季报', '12': '年报' } as Record<string, string>)[p.slice(5, 7)] || p}`
const PERIODS = computed(() => Object.entries(data.value?.periods || {})
  .sort(([a], [b]) => b.localeCompare(a))
  .map(([p, n]) => ({ value: p, label: `${periodName(p)} ${n}` })))
const chosen = computed({
  get: () => period.value || data.value?.period || null,
  set: (v: string | null) => { period.value = v },
})
const maxType = computed(() => Math.max(1, ...(data.value?.types || []).map((t) => t.count)))
const chg = (v: number | null) => (v === null ? '—' : `${v > 0 ? '+' : ''}${Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(1)}%`)
const typeClass = (t: string) => (['预增', '略增', '扭亏', '续盈', '减亏'].includes(t) ? 'up' : t === '不确定' ? 'muted' : 'down')
const open = (r: ForecastRow) => router.push(`/stock/${r.code}`)
</script>

<template>
  <section class="card wide">
    <div class="head">
      <h3>业绩预告</h3>
      <SelectButton v-if="PERIODS.length" v-model="chosen" :options="PERIODS" option-label="label" option-value="value" :allow-empty="false" size="small" />
    </div>
    <p v-if="error" class="bad small">{{ error }}</p>
    <p v-else-if="loading && !data" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p v-else-if="data && !data.available" class="muted small">{{ data.note }}</p>
    <template v-else-if="data">
      <p class="sum">
        {{ periodName(data.period!) }}：截至 {{ data.date }} 共 <b>{{ data.count }}</b> 家发布净利润预告，
        其中<b class="up">预喜 {{ data.good }} 家（{{ data.good_share?.toFixed(1) }}%）</b>
      </p>
      <p class="muted small sub">每家公司只计归属母公司净利润的预告。预喜 = 预增、略增、扭亏、续盈、减亏；预忧 = 预减、略减、首亏、续亏。
        <b>预喜比例高、集中在某些行业</b>，说明这些行业景气向上，可与行业涨跌互相印证；按选中交易日之前公告的统计。</p>
      <div class="grid">
        <div>
          <div class="muted small">预告类型</div>
          <div v-for="t in data.types" :key="t.type" class="tbar">
            <span class="tname" :class="typeClass(t.type)">{{ t.type }}</span>
            <span class="ttrack"><span class="tfill" :style="{ width: `${(t.count / maxType) * 100}%`, background: t.good ? 'var(--up)' : t.type === '不确定' ? '#9aa4b2' : 'var(--down)' }" /></span>
            <span class="tval">{{ t.count }}</span>
          </div>
        </div>
        <div>
          <div class="muted small">按行业（申万一级）</div>
          <DataTable :value="data.industries" data-key="name" scrollable scroll-height="260px" size="small" striped-rows removable-sort class="fc">
            <Column field="name" header="行业" sortable />
            <Column field="count" header="家数" sortable header-class="nr" body-class="nr" />
            <Column field="good_share" header="预喜占比" sortable header-class="nr" body-class="nr">
              <template #body="{ data: r }"><span :class="(r.good_share ?? 0) >= 70 ? 'up' : (r.good_share ?? 100) <= 40 ? 'down' : ''">{{ r.good_share === null ? '—' : `${r.good_share.toFixed(0)}%` }}</span></template>
            </Column>
            <Column field="median_chg" header="中位变动" sortable header-class="nr" body-class="nr">
              <template #body="{ data: r }"><span :class="upDownClass(r.median_chg)">{{ chg(r.median_chg) }}</span></template>
            </Column>
          </DataTable>
        </div>
      </div>
      <div class="grid lists">
        <div v-for="list in ([['净利润变动幅度最大', data.best], ['最新公告', data.latest]] as const)" :key="list[0]">
          <div class="muted small">{{ list[0] }}</div>
          <table class="flist">
            <tr v-for="r in list[1]" :key="`${r.code}-${r.date}`" :title="r.what">
              <td><a class="link" @click="open(r)">{{ r.name }}</a></td>
              <td :class="typeClass(r.type)">{{ r.type }}</td>
              <td class="nr" :class="upDownClass(r.chg)">{{ chg(r.chg) }}</td>
              <td class="muted">{{ r.industry || '' }}</td>
              <td class="muted nr">{{ r.date.slice(5) }}</td>
            </tr>
          </table>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.wide { grid-column: 1 / -1; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
h3 { margin: 0; font-size: 15px; }
.sum { margin: 8px 0; font-size: 13px; line-height: 1.6; }
.small { font-size: 12px; }
.sub { margin: 6px 0; }
.bad { color: var(--up); }
.grid { display: grid; grid-template-columns: 1fr 1.4fr; gap: 20px; margin-top: 8px; }
.grid.lists { grid-template-columns: 1fr 1fr; }
@media (max-width: 900px) { .grid, .grid.lists { grid-template-columns: 1fr; } }
.tbar { display: grid; grid-template-columns: 44px 1fr 40px; gap: 8px; align-items: center; font-size: 12px; margin-top: 5px; }
.ttrack { height: 10px; background: #f1f3f6; border-radius: 3px; overflow: hidden; }
.tfill { display: block; height: 100%; border-radius: 3px; }
.tval { text-align: right; font-variant-numeric: tabular-nums; }
.flist { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 4px; font-variant-numeric: tabular-nums; }
.flist td { padding: 3px 4px; border-bottom: 1px solid #f1f3f6; white-space: nowrap; }
.flist .nr { text-align: right; }
.link { cursor: pointer; }
.link:hover { color: var(--up); }
:deep(.fc th.nr), :deep(.fc td.nr) { text-align: right; font-variant-numeric: tabular-nums; }
:deep(.fc th.nr .p-datatable-column-header-content) { justify-content: flex-end; }
</style>
