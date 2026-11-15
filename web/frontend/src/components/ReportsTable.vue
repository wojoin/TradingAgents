<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import IconField from 'primevue/iconfield'
import InputIcon from 'primevue/inputicon'
import Tag from 'primevue/tag'
import { api, formatSize, ratingSeverity, type ReportMeta } from '../api'

// Saved reports: sortable, searchable, with downloads. ``ticker`` narrows it to one stock.
const props = defineProps<{ ticker?: string; title?: string; rows?: number }>()
const reports = ref<ReportMeta[]>([])
const loading = ref(false)
const error = ref('')
const filters = ref({ global: { value: null as string | null, matchMode: 'contains' } })
const table = ref<InstanceType<typeof DataTable>>()

const shown = computed(() => {
  if (!props.ticker) return reports.value
  const code = props.ticker.replace(/\..*$/, '')
  return reports.value.filter((r) => (r.ticker || '').replace(/\..*$/, '') === code)
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    reports.value = await api.reports()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
defineExpose({ reload: load })
</script>

<template>
  <DataTable
    ref="table"
    v-model:filters="filters"
    :value="shown"
    :loading="loading"
    data-key="id"
    sort-mode="multiple"
    removable-sort
    :multi-sort-meta="[{ field: 'generated', order: -1 }]"
    paginator
    :rows="rows || 10"
    :rows-per-page-options="[10, 20, 50]"
    :global-filter-fields="['ticker', 'analysis_date', 'rating', 'models']"
    export-filename="tradingagents-reports"
    striped-rows
    size="small"
  >
    <template #header>
      <div class="row between">
        <div class="row">
          <strong>{{ title || '分析报告' }}</strong>
          <span class="muted">共 {{ shown.length }} 份 · 按住 Ctrl/⌘ 点击表头可多列排序</span>
        </div>
        <div class="row">
          <IconField>
            <InputIcon class="pi pi-search" />
            <InputText v-model="filters.global.value" placeholder="搜索代码、日期、评级" />
          </IconField>
          <Button icon="pi pi-refresh" severity="secondary" text aria-label="刷新" @click="load" />
          <Button label="导出 CSV" icon="pi pi-file-export" severity="secondary" outlined @click="table?.exportCSV()" />
        </div>
      </div>
    </template>
    <template #empty>
      <span class="muted">{{ error ? `报告列表加载失败：${error}` : '还没有报告。发起一次分析后，报告会出现在这里。' }}</span>
    </template>
    <Column field="ticker" header="代码" sortable>
      <template #body="{ data }">
        <RouterLink :to="`/reports/${data.id}`" class="link">{{ data.ticker || data.id }}</RouterLink>
      </template>
    </Column>
    <Column field="analysis_date" header="分析日" sortable />
    <Column field="rating" header="评级" sortable>
      <template #body="{ data }">
        <Tag v-if="data.rating" :value="data.rating" :severity="ratingSeverity(data.rating)" />
      </template>
    </Column>
    <Column field="generated" header="生成时间" sortable />
    <Column field="models" header="模型" sortable class="models" />
    <Column field="size" header="大小" sortable>
      <template #body="{ data }">{{ formatSize(data.size) }}</template>
    </Column>
    <Column header="下载" :exportable="false">
      <template #body="{ data }">
        <div class="row nowrap">
          <a :href="api.download(data.id, 'md')" download><Button label="MD" size="small" text /></a>
          <a v-if="data.has_html" :href="api.download(data.id, 'html')" download><Button label="HTML" size="small" text /></a>
          <a :href="api.download(data.id, 'zip')" download><Button label="ZIP" size="small" text /></a>
        </div>
      </template>
    </Column>
  </DataTable>
</template>

<style scoped>
.between { justify-content: space-between; width: 100%; }
.link { color: #2563eb; text-decoration: none; font-weight: 600; }
.nowrap { flex-wrap: nowrap; gap: 0; }
a { text-decoration: none; }
:deep(.models) { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
