<script setup lang="ts">
import { computed, onMounted, ref, watch as watchRef } from 'vue'
import { useRouter } from 'vue-router'
import DataTable, { type DataTableSortMeta } from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import { useToast } from 'primevue/usetoast'
import { api, formatLots, formatPct, formatYuan, upDownClass, type Watchlist, type WatchRow } from '../api'
import { DEFAULT_GROUP, useWatchlist } from '../watchlist'
import { useLongPress } from '../longPress'
import StockMenu from '../components/StockMenu.vue'
import GroupDialog from '../components/GroupDialog.vue'
import StockPicker from '../components/StockPicker.vue'

// 自选: the groups along the top; the chosen group's stocks in a sortable table below.
const router = useRouter()
const toast = useToast()
const watchlist = useWatchlist()
const data = ref<Watchlist | null>(null)
const loading = ref(false)
const picker = ref<InstanceType<typeof StockPicker>>()
const KEY = 'watchlist.group'
const selected = ref<string | null>(stored())
const dialog = ref<{ mode: 'create' | 'edit'; open: boolean; busy: boolean; error: string }>({
  mode: 'create', open: false, busy: false, error: '',
})
const confirmDelete = ref(false)

function stored(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}
watchRef(selected, (v) => {
  try {
    if (v) localStorage.setItem(KEY, v)
  } catch {
    /* storage unavailable */
  }
})

const groups = computed(() => watchlist.state.groups)
const group = computed(() => groups.value.find((g) => g.id === selected.value) || null)
const rows = computed<WatchRow[]>(() =>
  (group.value?.codes || []).map((c) => data.value?.rows?.[c] || { code: c, name: null, missing: true }),
)

async function load() {
  loading.value = true
  try {
    data.value = await api.watchlist()
    await watchlist.load()
    if (!group.value) selected.value = groups.value[0]?.id ?? null
  } catch (e) {
    toast.add({ severity: 'error', summary: '自选加载失败', detail: e instanceof Error ? e.message : String(e), life: 5000 })
  } finally {
    loading.value = false
  }
}

function openDialog(mode: 'create' | 'edit') {
  dialog.value = { mode, open: true, busy: false, error: '' }
}

async function saveGroup(name: string, color: string) {
  dialog.value.busy = true
  dialog.value.error = ''
  try {
    if (dialog.value.mode === 'create') {
      const g = await watchlist.create(name, color)
      selected.value = g.id
    } else if (group.value) {
      await watchlist.update(group.value.id, { name, color })
    }
    dialog.value.open = false
  } catch (e) {
    dialog.value.error = e instanceof Error ? e.message : String(e)
  } finally {
    dialog.value.busy = false
  }
}

async function deleteGroup() {
  if (!group.value) return
  await watchlist.remove(group.value.id)
  confirmDelete.value = false
  selected.value = groups.value[0]?.id ?? null
}

async function addStock(value: string) {
  if (!group.value) return
  let code = value.trim()
  if (!/^\d{6}$/.test(code.replace(/\.(SH|SS|SZ|BJ)$/i, '').replace(/^(SH|SZ|BJ)/i, ''))) {
    const hits = await api.search(code, 2).catch(() => [])
    if (!hits.length) return toast.add({ severity: 'warn', summary: '找不到股票', detail: value, life: 4000 })
    code = hits[0].code
  }
  try {
    await watchlist.add(group.value.id, code)
    picker.value?.clear()
    if (!data.value?.rows?.[code.replace(/\D/g, '').slice(-6)]) await load()
  } catch (e) {
    toast.add({ severity: 'error', summary: '无法加入', detail: e instanceof Error ? e.message : String(e), life: 5000 })
  }
}

async function removeStock(code: string) {
  if (group.value) await watchlist.drop(group.value.id, code)
}

const num = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? '—' : v.toFixed(d))

// ---- Row menu: long-press a row (or right-click it) for groups, move to top / bottom, and a note.
const stockMenu = ref<InstanceType<typeof StockMenu>>()
const sortMeta = ref<DataTableSortMeta[]>([])   // cleared on a move, to show the group's order
const nameOf = (code: string) => data.value?.rows?.[code]?.name || code
const press = useLongPress((e, code) => stockMenu.value?.open(e, code, nameOf(code)))

function onRowClick(e: { data: WatchRow }) {
  if (press.swallowed()) return
  if (!e.data.missing) router.push(`/stock/${e.data.code}`)
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="card groups">
      <button v-for="g in groups" :key="g.id" class="chip" :class="{ on: g.id === selected }"
              :style="{ '--c': g.color }" @click="selected = g.id">
        <span class="dot" />
        <span>{{ g.name }}</span>
        <span class="count">{{ g.codes.length }}</span>
      </button>
      <button v-if="groups.length < watchlist.state.max" class="chip add" @click="openDialog('create')">
        <i class="pi pi-plus" /> 新建分组
      </button>
      <span class="muted small spacer">{{ groups.length }} / {{ watchlist.state.max }} 组</span>
      <Button icon="pi pi-refresh" severity="secondary" text aria-label="刷新" @click="load" />
    </div>

    <div v-if="!groups.length && !loading" class="card muted empty">
      还没有自选分组。点「新建分组」建一个，或在「行情」「个股」里点 <i class="pi pi-star" /> 时新建。
    </div>

    <div v-if="group" class="card" v-on="press.handlers">
      <DataTable
        v-model:multi-sort-meta="sortMeta"
        :value="rows"
        :loading="loading"
        context-menu
        data-key="code"
        sort-mode="multiple"
        removable-sort
        reorderable-columns
        state-storage="local"
        state-key="watchlist.group.table.v1"
        scrollable
        striped-rows
        size="small"
        row-hover
        class="watch"
        @row-click="onRowClick"
        @row-contextmenu="(e) => stockMenu?.open(e.originalEvent, e.data.code, e.data.name)"
      >
        <template #header>
          <div class="row between">
            <div class="row">
              <span class="dot big" :style="{ background: group.color }" />
              <strong>{{ group.name }}</strong>
              <span class="muted">{{ group.codes.length }} 只<template v-if="data?.date"> · 行情日 {{ data.date }}</template></span>
              <StockPicker ref="picker" placeholder="加入本组：代码或名称" @select="addStock" @submit="addStock" />
            </div>
            <div class="row">
              <span v-if="data?.ttm" class="muted small">TTM：{{ data.ttm }}</span>
              <Button v-if="group.id !== DEFAULT_GROUP" label="编辑分组" icon="pi pi-pencil" severity="secondary" text size="small"
                      @click="openDialog('edit')" />
              <Button v-if="group.id !== DEFAULT_GROUP" label="删除分组" icon="pi pi-trash" severity="danger" text size="small"
                      @click="confirmDelete = true" />
            </div>
          </div>
          <div v-if="data?.flow && data.flow.source !== 'eastmoney'" class="muted small note">
            <i class="pi pi-info-circle" /> {{ data.flow.note }}
          </div>
        </template>
        <template #empty><span class="muted">这个分组还没有股票。用上面的输入框加入，或在「行情」「个股」里点 <i class="pi pi-star" />。</span></template>
        <Column field="code" header="代码" sortable column-key="code">
          <template #body="{ data: r }"><span :data-code="r.code">{{ r.code }}</span></template>
        </Column>
        <Column field="name" header="名称" sortable column-key="name">
          <template #body="{ data: r }">
            <strong>{{ r.name || '—' }}</strong><span v-if="r.missing" class="muted small"> 无行情</span>
            <i v-if="watchlist.state.notes[r.code]" class="pi pi-file-edit note-mark" :title="watchlist.state.notes[r.code].text" />
          </template>
        </Column>
        <Column field="pct_chg" header="涨幅" sortable column-key="pct_chg">
          <template #body="{ data: r }"><span :class="upDownClass(r.pct_chg)">{{ formatPct(r.pct_chg) }}</span></template>
        </Column>
        <Column field="price" header="现价" sortable column-key="price">
          <template #body="{ data: r }"><span :class="upDownClass(r.pct_chg)">{{ num(r.price) }}</span></template>
        </Column>
        <Column field="volume" header="成交量" sortable column-key="volume">
          <template #body="{ data: r }">{{ formatLots(r.volume) }}</template>
        </Column>
        <Column field="amount" header="成交额" sortable column-key="amount">
          <template #body="{ data: r }">{{ formatYuan(r.amount) }}</template>
        </Column>
        <Column field="pct_5d" header="5日涨幅" sortable column-key="pct_5d">
          <template #body="{ data: r }"><span :class="upDownClass(r.pct_5d)">{{ formatPct(r.pct_5d) }}</span></template>
        </Column>
        <Column field="main_flow" :header="data?.flow?.label || '主力净流入'" sortable column-key="main_flow">
          <template #body="{ data: r }"><span :class="upDownClass(r.main_flow)">{{ formatYuan(r.main_flow, true) }}</span></template>
        </Column>
        <Column field="turnover" header="换手率%" sortable column-key="turnover">
          <template #body="{ data: r }">{{ num(r.turnover) }}</template>
        </Column>
        <Column field="pe_ttm" header="市盈TTM" sortable column-key="pe_ttm">
          <template #body="{ data: r }">{{ num(r.pe_ttm) }}</template>
        </Column>
        <Column header="" :reorderable-column="false" :exportable="false" column-key="remove" style="width: 44px">
          <template #body="{ data: r }">
            <button class="remove" title="移出本组" @click.stop="removeStock(r.code)"><i class="pi pi-times" /></button>
          </template>
        </Column>
      </DataTable>
    </div>

    <StockMenu ref="stockMenu" :group-id="group?.id" @moved="sortMeta = []" />
    <GroupDialog v-model:visible="dialog.open" :title="dialog.mode === 'create' ? '新建分组' : '编辑分组'"
                 :name="dialog.mode === 'edit' ? group?.name : ''" :color="dialog.mode === 'edit' ? group?.color : undefined"
                 :busy="dialog.busy" :error="dialog.error" @save="saveGroup" />
    <Dialog v-model:visible="confirmDelete" modal header="删除分组" :style="{ width: '360px' }">
      确定删除分组「{{ group?.name }}」？组内 {{ group?.codes.length }} 只股票会从这个分组移除（不影响其他分组）。
      <template #footer>
        <Button label="取消" severity="secondary" text @click="confirmDelete = false" />
        <Button label="删除" severity="danger" @click="deleteGroup" />
      </template>
    </Dialog>
  </div>
</template>

<style scoped>
.page > * + * { margin-top: 8px; }
.groups { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 10px 12px; }
.chip {
  display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; border-radius: 999px;
  border: 1px solid var(--border); background: #fff; cursor: pointer; font: inherit; font-size: 13px; color: var(--text);
}
.chip:hover { border-color: var(--c, #9ca3af); }
.chip.on { background: var(--c); border-color: var(--c); color: #fff; }
.chip .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--c); }
.chip.on .dot { background: #fff; }
.chip .count { font-size: 12px; opacity: 0.75; }
.chip.add { border-style: dashed; color: var(--muted); }
.spacer { margin-left: auto; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.dot.big { width: 12px; height: 12px; }
.between { justify-content: space-between; width: 100%; }
.small { font-size: 12px; }
.note { margin-top: 8px; }
.empty { text-align: center; padding: 40px 16px; }
:deep(.watch th), :deep(.watch td) { text-align: left; white-space: nowrap; font-variant-numeric: tabular-nums; }
:deep(.watch th .p-datatable-column-header-content) { justify-content: flex-start; }
:deep(.watch tbody tr) { cursor: pointer; }
.remove { border: 0; background: none; cursor: pointer; color: #9ca3af; padding: 2px 4px; }
.note-mark { color: #f59e0b; margin-left: 6px; font-size: 12px; }
:deep(.watch tbody tr) { user-select: none; -webkit-touch-callout: none; }
.remove:hover { color: var(--up); }
</style>
