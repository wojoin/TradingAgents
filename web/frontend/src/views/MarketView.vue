<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import IconField from 'primevue/iconfield'
import InputIcon from 'primevue/inputicon'
import Select from 'primevue/select'
import DatePicker from 'primevue/datepicker'
import Message from 'primevue/message'
import { api, formatLots, formatPct, formatShares, formatYuan, upDownClass, type MarketCalendar, type MarketRow, type MarketTable } from '../api'
import WatchStar from '../components/WatchStar.vue'
import StockMenu from '../components/StockMenu.vue'
import { useLongPress } from '../longPress'
import { useWatchlist } from '../watchlist'

// The whole A-share market on one trading day, from the local AKShare store: every row
// in one scrolling table (virtualised, so only the visible rows are drawn).
const ROW_HEIGHT = 36
const router = useRouter()
const watchlist = useWatchlist()
// Long-press a row (or right-click it) for its menu: groups, note, open, analyse.
const stockMenu = ref<InstanceType<typeof StockMenu>>()
const nameOf = (code: string) => table.value?.rows.find((r) => r.code === code)?.name || code
const press = useLongPress((e, code) => stockMenu.value?.open(e, code, nameOf(code)))
const fix = (v: number | null | undefined, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? '—' : v.toFixed(d))
const table = ref<MarketTable | null>(null)
const loading = ref(false)
const error = ref('')
const date = ref<string | null>(null)
// The trading-day calendar: weekends and holidays cannot be picked.
const cal = ref<MarketCalendar | null>(null)
const picked = ref<Date | null>(null)
const toDate = (s: string) => new Date(`${s}T00:00:00`)
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const holidays = computed(() => (cal.value?.holidays || []).map(toDate))
const industry = ref<string | null>(null)
const dt = ref<InstanceType<typeof DataTable>>()
const filters = ref({
  global: { value: null as string | null, matchMode: 'contains' },
})

const industries = computed(() =>
  [...new Set((table.value?.rows || []).map((r) => r.industry).filter((x): x is string => !!x))].sort((a, b) =>
    a.localeCompare(b, 'zh-CN'),
  ),
)
// The universe: all A-shares, by exchange, the CSI 300, or ST stocks; remembered in this browser.
type Universe = 'all' | 'shsz' | 'hs300' | 'sh' | 'sz' | 'bj' | 'st'
const UNIVERSES: { value: Universe; label: string }[] = [
  { value: 'all', label: '全部A股' }, { value: 'shsz', label: '沪深A股' }, { value: 'hs300', label: '沪深300' },
  { value: 'sh', label: '沪市A股' }, { value: 'sz', label: '深市A股' }, { value: 'bj', label: '京市A股' },
  { value: 'st', label: 'ST股' },
]
const UNIVERSE_KEY = 'market.universe'
function storedUniverse(): Universe {
  try {
    const v = localStorage.getItem(UNIVERSE_KEY)
    return (UNIVERSES.some((u) => u.value === v) ? v : 'all') as Universe
  } catch {
    return 'all'
  }
}
const universe = ref<Universe>(storedUniverse())
const hs300 = ref<{ codes: Set<string>; asOf: string | null } | null>(null)
const universeError = ref('')

async function loadHs300() {
  if (hs300.value) return
  try {
    const m = await api.indexMembers('000300')
    hs300.value = { codes: new Set(m.codes), asOf: m.as_of }
    universeError.value = ''
  } catch (e) {
    universeError.value = `沪深300成分股取不到：${e instanceof Error ? e.message : String(e)}`
  }
}
watch(universe, (v) => {
  try {
    localStorage.setItem(UNIVERSE_KEY, v)
  } catch {
    /* storage unavailable */
  }
  if (v === 'hs300') loadHs300()
})

function inUniverse(r: MarketRow): boolean {
  switch (universe.value) {
    case 'shsz': return r.exchange === 'SH' || r.exchange === 'SZ'
    case 'sh': return r.exchange === 'SH'
    case 'sz': return r.exchange === 'SZ'
    case 'bj': return r.exchange === 'BJ'
    case 'st': return /ST/i.test(r.name)
    case 'hs300': return !!hs300.value?.codes.has(r.code)
    default: return true
  }
}

const rows = computed(() => {
  const all = (table.value?.rows || []).filter(inUniverse)
  return industry.value ? all.filter((r) => r.industry === industry.value) : all
})
// The day's count of stocks and of rises, falls and unchanged: the whole market, or the
// chosen industry when one is picked.
const breadth = computed(() => {
  if (!industry.value && universe.value === 'all' && table.value?.breadth) return table.value.breadth
  const r = rows.value
  const up = r.filter((x) => (x.pct_chg ?? 0) > 0).length
  const down = r.filter((x) => (x.pct_chg ?? 0) < 0).length
  return { total: r.length, up, down, flat: r.length - up - down }
})

async function load(d?: string | null) {
  loading.value = true
  error.value = ''
  try {
    table.value = await api.market(d || undefined)
    date.value = table.value.date
    picked.value = toDate(table.value.date)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function pick(d: Date | Date[] | (Date | null)[] | null | undefined) {
  if (d instanceof Date && iso(d) !== date.value) load(iso(d))
}

onMounted(async () => {
  load()
  if (universe.value === 'hs300') loadHs300()
  cal.value = await api.marketCalendar().catch(() => null)
})
</script>

<template>
  <!-- One screen: the table fills what the page leaves, the notes sit at the very bottom. -->
  <div class="page fill">
    <Message v-if="error" severity="error" class="gap">行情加载失败：{{ error }}</Message>
    <div class="card fill-card" v-on="press.handlers">
      <DataTable
        ref="dt"
        v-model:filters="filters"
        :value="rows"
        :loading="loading"
        data-key="code"
        sort-mode="multiple"
        removable-sort
        :multi-sort-meta="[{ field: 'pct_chg', order: -1 }]"
        scrollable
        scroll-height="flex"
        :virtual-scroller-options="{ itemSize: ROW_HEIGHT }"
        table-style="table-layout: fixed; min-width: 2036px"
        :global-filter-fields="['code', 'name', 'industry', 'sub_industry']"
        :export-filename="`a-share-market-${date}`"
        striped-rows
        size="small"
        row-hover
        context-menu
        class="market"
        @row-click="(e) => !press.swallowed() && router.push(`/stock/${e.data.code}`)"
        @row-contextmenu="(e) => stockMenu?.open(e.originalEvent, e.data.code, e.data.name)"
      >
        <template #header>
          <div class="row between">
            <div class="row">
              <Select v-model="universe" :options="UNIVERSES" option-label="label" option-value="value" class="universe" />
              <DatePicker v-model="picked" date-format="yy-mm-dd" show-icon :manual-input="false" class="date"
                          :min-date="cal?.min ? toDate(cal.min) : undefined" :max-date="cal?.max ? toDate(cal.max) : undefined"
                          :disabled-dates="holidays" :disabled-days="[0, 6]" :disabled="loading"
                          @update:model-value="pick" />
              <span v-if="loading" class="muted small"><i class="pi pi-spin pi-spinner" /> 载入中（历史日期首次约需数秒）</span>
              <span v-else-if="table" class="muted">
                {{ industry ? `${industry} ` : '' }}共 {{ breadth.total }} 只 · <span class="up">涨 {{ breadth.up }}</span> ·
                <span class="down">跌 {{ breadth.down }}</span> · 平 {{ breadth.flat }}
              </span>
              <span v-if="table?.ttm" class="muted small">TTM：{{ table.ttm }}</span>
            </div>
            <div class="row">
              <Select v-model="industry" :options="industries" placeholder="全部行业" show-clear filter class="industry" />
              <IconField>
                <InputIcon class="pi pi-search" />
                <InputText v-model="filters.global.value" placeholder="代码、名称或行业" />
              </IconField>
              <Button label="导出 CSV" icon="pi pi-file-export" severity="secondary" outlined @click="dt?.exportCSV()" />
            </div>
          </div>

        </template>
        <template #empty><span class="muted">没有匹配的股票</span></template>
        <!-- The row's position as shown, after sorting and filtering: 1, 2, 3 ... from the top. -->
        <Column header="" :exportable="false" header-class="nr" body-class="nr seq" style="width: 60px">
          <template #body="{ index }">{{ index + 1 }}</template>
        </Column>
        <Column header="" :exportable="false" header-class="txt" body-class="txt" style="width: 44px">
          <template #body="{ data }"><WatchStar :code="data.code" /></template>
        </Column>
        <Column field="code" header="代码" sortable header-class="txt" body-class="txt num" style="width: 80px">
          <template #body="{ data }"><span :data-code="data.code">{{ data.code }}</span></template>
        </Column>
        <Column field="name" header="名称" sortable header-class="txt" body-class="txt" style="width: 100px">
          <template #body="{ data }">
            <strong>{{ data.name }}</strong>
            <i v-if="watchlist.state.notes[data.code]" class="pi pi-file-edit note-mark" :title="watchlist.state.notes[data.code].text" />
          </template>
        </Column>
        <Column field="pct_chg" header="涨幅" sortable header-class="nr" body-class="nr" style="width: 84px">
          <template #body="{ data }"><span :class="upDownClass(data.pct_chg)">{{ formatPct(data.pct_chg) }}</span></template>
        </Column>
        <Column field="price" header="现价" sortable header-class="nr" body-class="nr" style="width: 84px">
          <template #body="{ data }"><span :class="upDownClass(data.pct_chg)">{{ fix(data.price) }}</span></template>
        </Column>
        <Column field="main_flow" :header="table?.flow.label || '主力净流入'" sortable header-class="nr" body-class="nr" style="width: 140px">
          <template #body="{ data }"><span :class="upDownClass(data.main_flow)">{{ formatYuan(data.main_flow, true) }}</span></template>
        </Column>
        <Column field="open_pct" header="开盘涨幅" sortable header-class="nr" body-class="nr" style="width: 90px">
          <template #body="{ data }"><span :class="upDownClass(data.open_pct)">{{ formatPct(data.open_pct) }}</span></template>
        </Column>
        <Column field="high" header="最高" sortable header-class="nr" body-class="nr" style="width: 84px">
          <template #body="{ data }">{{ fix(data.high) }}</template>
        </Column>
        <Column field="low" header="最低" sortable header-class="nr" body-class="nr" style="width: 84px">
          <template #body="{ data }">{{ fix(data.low) }}</template>
        </Column>
        <Column field="amount" header="成交额" sortable header-class="nr" body-class="nr" style="width: 96px">
          <template #body="{ data }">{{ formatYuan(data.amount) }}</template>
        </Column>
        <Column field="volume" header="成交量" sortable header-class="nr" body-class="nr" style="width: 104px">
          <template #body="{ data }">{{ formatLots(data.volume) }}</template>
        </Column>
        <Column field="pct_5d" header="5日涨幅" sortable header-class="nr" body-class="nr" style="width: 90px">
          <template #body="{ data }"><span :class="upDownClass(data.pct_5d)">{{ formatPct(data.pct_5d) }}</span></template>
        </Column>
        <Column field="amplitude" header="振幅" sortable header-class="nr" body-class="nr" style="width: 84px">
          <template #body="{ data }">{{ formatPct(data.amplitude, false) }}</template>
        </Column>
        <Column field="industry" header="所属行业" sortable header-class="txt" body-class="txt" style="width: 100px">
          <template #body="{ data }"><span :title="data.sub_industry || ''">{{ data.industry || '—' }}</span></template>
        </Column>
        <Column field="turnover" header="换手率%" sortable header-class="nr" body-class="nr" style="width: 84px">
          <template #body="{ data }">{{ fix(data.turnover) }}</template>
        </Column>
        <Column field="pe_ttm" header="市盈TTM" sortable header-class="nr" body-class="nr" style="width: 90px">
          <template #body="{ data }">{{ fix(data.pe_ttm) }}</template>
        </Column>
        <Column field="eps_ttm" header="每股收益TTM" sortable header-class="nr" body-class="nr" style="width: 110px">
          <template #body="{ data }">{{ fix(data.eps_ttm, 3) }}</template>
        </Column>
        <Column field="total_mv" header="总市值" sortable header-class="nr" body-class="nr" style="width: 96px">
          <template #body="{ data }">{{ formatYuan(data.total_mv) }}</template>
        </Column>
        <Column field="total_shares" header="总股本" sortable header-class="nr" body-class="nr" style="width: 90px">
          <template #body="{ data }">{{ formatShares(data.total_shares) }}</template>
        </Column>
        <Column field="float_mv" header="流通值" sortable header-class="nr" body-class="nr" style="width: 96px">
          <template #body="{ data }">{{ formatYuan(data.float_mv) }}</template>
        </Column>
        <Column field="float_shares" header="流通股" sortable header-class="nr" body-class="nr" style="width: 90px">
          <template #body="{ data }">{{ formatShares(data.float_shares) }}</template>
        </Column>
      </DataTable>
      <StockMenu ref="stockMenu" extras />
      <!-- The bottom bar: what the figures rest on. -->
      <div class="bottom">
        <span v-if="universe === 'hs300' && hs300?.asOf" class="muted small">成分股名单 {{ hs300.asOf }}（中证指数公司）</span>
        <span v-if="universeError" class="bad small">{{ universeError }}</span>
        <span class="notes">
          <span v-if="table && table.flow.source !== 'eastmoney'" class="muted small"><i class="pi pi-info-circle" /> {{ table.flow.note }}</span>
          <span v-if="table?.note" class="muted small"><i class="pi pi-info-circle" /> {{ table.note }}</span>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.gap { margin-bottom: 12px; }
.fill { height: 100vh; display: flex; flex-direction: column; padding-bottom: 8px; }
.fill-card { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.fill-card > :deep(.market) { flex: 1; min-height: 0; }
.bottom { flex: none; }
/* Narrow screens put the menu on top: the table takes most of the screen instead. */
@media (max-width: 760px) {
  .fill { height: auto; }
  .fill-card { height: 75vh; }
}
.between { justify-content: space-between; width: 100%; }
.date { width: 160px; }
.industry { width: 170px; }
.note { margin-top: 8px; font-size: 12px; }
.bottom { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); }
.universe { width: 130px; }
.notes { display: flex; flex-direction: column; gap: 2px; margin-left: auto; text-align: right; }
.bottom:empty { display: none; }
.bad { color: var(--up); }
.small { font-size: 12px; }
/* One alignment per column, header and cells alike: text left, numbers right. */
:deep(.market th.txt), :deep(.market td.txt) { text-align: left; }
:deep(.market th.txt .p-datatable-column-header-content) { justify-content: flex-start; }
:deep(.market th.nr), :deep(.market td.nr) { text-align: right; }
:deep(.market th.nr .p-datatable-column-header-content) { justify-content: flex-end; }
:deep(.market td.nr), :deep(.market td.num) { font-variant-numeric: tabular-nums; }
/* Fixed row height: the virtual scroller places rows by it. */
:deep(.market tbody tr) { height: 36px; cursor: pointer; }
:deep(.market td) { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-top: 0; padding-bottom: 0; }
:deep(.market th) { white-space: nowrap; }
:deep(.market tbody tr) { user-select: none; -webkit-touch-callout: none; }
.note-mark { color: #f59e0b; margin-left: 4px; font-size: 11px; }
:deep(.market td.seq) { color: var(--muted); padding-right: 16px; }
</style>
