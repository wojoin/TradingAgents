<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import IconField from 'primevue/iconfield'
import InputIcon from 'primevue/inputicon'
import Select from 'primevue/select'
import Message from 'primevue/message'
import { api, formatLots, formatPct, formatYuan, upDownClass, type MarketTable } from '../api'

// The whole A-share market on one trading day, from the local AKShare store: every row
// in one scrolling table (virtualised, so only the visible rows are drawn).
const ROW_HEIGHT = 36
const router = useRouter()
const table = ref<MarketTable | null>(null)
const loading = ref(false)
const error = ref('')
const date = ref<string | null>(null)
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
const rows = computed(() => {
  const all = table.value?.rows || []
  return industry.value ? all.filter((r) => r.industry === industry.value) : all
})
const breadth = computed(() => {
  const r = rows.value
  return {
    up: r.filter((x) => (x.pct_chg ?? 0) > 0).length,
    down: r.filter((x) => (x.pct_chg ?? 0) < 0).length,
    flat: r.filter((x) => x.pct_chg === 0).length,
  }
})

async function load(d?: string | null) {
  loading.value = true
  error.value = ''
  try {
    table.value = await api.market(d || undefined)
    date.value = table.value.date
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => load())
</script>

<template>
  <div class="page">
    <Message v-if="error" severity="error" class="gap">行情加载失败：{{ error }}</Message>
    <div class="card">
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
        scroll-height="calc(100vh - 210px)"
        :virtual-scroller-options="{ itemSize: ROW_HEIGHT }"
        table-style="table-layout: fixed; min-width: 1100px"
        :global-filter-fields="['code', 'name', 'industry', 'sub_industry']"
        :export-filename="`a-share-market-${date}`"
        striped-rows
        size="small"
        row-hover
        class="market"
        @row-click="(e) => router.push(`/stock/${e.data.code}`)"
      >
        <template #header>
          <div class="row between">
            <div class="row">
              <strong>全 A 行情</strong>
              <Select v-model="date" :options="table?.dates || []" placeholder="交易日" class="date" @change="load(date)" />
              <span v-if="table" class="muted">
                {{ rows.length }} 只 · <span class="up">涨 {{ breadth.up }}</span> ·
                <span class="down">跌 {{ breadth.down }}</span> · 平 {{ breadth.flat }}
              </span>
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
          <div v-if="table?.flow.source !== 'eastmoney' && table" class="muted note">
            <i class="pi pi-info-circle" /> {{ table.flow.note }}
          </div>
        </template>
        <template #empty><span class="muted">没有匹配的股票</span></template>
        <!-- The row's position as shown, after sorting and filtering: 1, 2, 3 ... from the top. -->
        <Column header="" :exportable="false" header-class="nr" body-class="nr seq" style="width: 60px">
          <template #body="{ index }">{{ index + 1 }}</template>
        </Column>
        <Column field="code" header="代码" sortable header-class="txt" body-class="txt num" style="width: 90px" />
        <Column field="name" header="名称" sortable header-class="txt" body-class="txt" style="width: 110px">
          <template #body="{ data }"><strong>{{ data.name }}</strong></template>
        </Column>
        <Column field="pct_chg" header="涨幅%" sortable header-class="nr" body-class="nr" style="width: 96px">
          <template #body="{ data }"><span :class="upDownClass(data.pct_chg)">{{ formatPct(data.pct_chg) }}</span></template>
        </Column>
        <Column field="price" header="现价" sortable header-class="nr" body-class="nr" style="width: 96px">
          <template #body="{ data }"><span :class="upDownClass(data.pct_chg)">{{ data.price?.toFixed(2) ?? '—' }}</span></template>
        </Column>
        <Column field="main_flow" :header="table?.flow.label || '主力净流入'" sortable header-class="nr" body-class="nr" style="width: 150px">
          <template #body="{ data }"><span :class="upDownClass(data.main_flow)">{{ formatYuan(data.main_flow, true) }}</span></template>
        </Column>
        <Column field="industry" header="行业" sortable header-class="txt" body-class="txt" style="width: 110px">
          <template #body="{ data }"><span :title="data.sub_industry || ''">{{ data.industry || '—' }}</span></template>
        </Column>
        <Column field="turnover" header="换手率%" sortable header-class="nr" body-class="nr" style="width: 100px">
          <template #body="{ data }">{{ data.turnover?.toFixed(2) ?? '—' }}</template>
        </Column>
        <Column field="amount" header="成交额" sortable header-class="nr" body-class="nr" style="width: 110px">
          <template #body="{ data }">{{ formatYuan(data.amount) }}</template>
        </Column>
        <Column field="volume" header="成交量" sortable header-class="nr" body-class="nr" style="width: 120px">
          <template #body="{ data }">{{ formatLots(data.volume) }}</template>
        </Column>
      </DataTable>
    </div>
  </div>
</template>

<style scoped>
.gap { margin-bottom: 12px; }
.between { justify-content: space-between; width: 100%; }
.date { width: 150px; }
.industry { width: 170px; }
.note { margin-top: 8px; font-size: 12px; }
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
:deep(.market td.seq) { color: var(--muted); padding-right: 16px; }
</style>
