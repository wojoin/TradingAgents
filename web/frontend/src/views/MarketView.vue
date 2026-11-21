<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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
import { ApiError, api, formatLots, formatPct, formatShares, formatYuan, upDownClass, type MarketCalendar, type MarketRow, type MarketSync, type MarketTable, type NotSynced, type SwClassStatus } from '../api'
import WatchStar from '../components/WatchStar.vue'
import StockMenu from '../components/StockMenu.vue'
import MarketStats from '../components/MarketStats.vue'
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

// 申万一级 → 二级 → 三级, cascading: each list holds what lies under the level above it, and
// picking a lower level fills in the levels above it.
const industry2 = ref<string | null>(null)
const industry3 = ref<string | null>(null)
const names = (xs: (string | null)[]) =>
  [...new Set(xs.filter((x): x is string => !!x))].sort((a, b) => a.localeCompare(b, 'zh-CN'))
const allRows = computed(() => table.value?.rows || [])
const industries = computed(() => names(allRows.value.map((r) => r.industry)))
const industries2 = computed(() =>
  names(allRows.value.filter((r) => !industry.value || r.industry === industry.value).map((r) => r.sub_industry)))
const industries3 = computed(() =>
  names(allRows.value.filter((r) => (!industry.value || r.industry === industry.value)
    && (!industry2.value || r.sub_industry === industry2.value)).map((r) => r.industry3)))
watch(industry, () => {
  if (industry2.value && !industries2.value.includes(industry2.value)) industry2.value = null
  if (industry3.value && !industries3.value.includes(industry3.value)) industry3.value = null
})
watch(industry2, (v) => {
  const r = v ? allRows.value.find((x) => x.sub_industry === v) : null
  if (r && r.industry !== industry.value) industry.value = r.industry
  if (industry3.value && !industries3.value.includes(industry3.value)) industry3.value = null
})
watch(industry3, (v) => {
  const r = v ? allRows.value.find((x) => x.industry3 === v) : null
  if (!r) return
  if (r.industry !== industry.value) industry.value = r.industry
  if (r.sub_industry !== industry2.value) industry2.value = r.sub_industry
})
// The most specific industry picked, for the count beside the date.
const picked3 = computed(() => industry3.value || industry2.value || industry.value)
// 三级行业 comes from 申万's own files kept locally; where they have nothing, from 乐咕乐股's
// copy (marked so). 乐咕乐股's set downloads by itself only while 申万's files are missing.
type Sw3 = NonNullable<MarketTable['sw3']>
const sw3 = ref<Sw3 | null>(null)
const swc = ref<SwClassStatus | null>(null)
watch(() => table.value?.sw3, (s) => { if (s) setSw3(s) })
watch(() => table.value?.sw_class, (s) => { if (s) swc.value = s })
const lgCount = computed(() => allRows.value.filter((r) => r.industry3_src === 'lg').length)
const sw3Hint = computed(() => (sw3.value && !swc.value?.ready && !sw3.value.ready && sw3.value.error ? '三级行业暂不可用' : '三级行业'))
// Tooltip: what 申万 published, when it was last checked and changed, and what changed then.
const sw3Info = computed(() => {
  const s = swc.value
  if (!s?.ready) return '申万官方分类文件尚未同步：三级行业来自乐咕乐股（可能不全）。点右侧按钮下载并同步。'
  const c = s.last_change
  return [`申万官方行业分类：数据截至 ${s.as_of || '—'}，${s.checked || '—'} 检查（每月一次，有变动才更新本地缓存）`,
    s.updated ? `本地缓存最后更新于 ${s.updated}` : '',
    c ? `${c.date} 变动：新增 ${c.added} 只、剔除 ${c.removed} 只、调整行业 ${c.moved} 只` : '',
    lgCount.value ? `另有 ${lgCount.value} 只的三级取自乐咕乐股` : ''].filter(Boolean).join('\n')
})
let sw3Timer = 0
function setSw3(st: Sw3) {
  const was = sw3.value?.building
  sw3.value = st
  window.clearTimeout(sw3Timer)
  if (st.building) sw3Timer = window.setTimeout(checkSw3, 5000)
  else if (was && st.ready) load(date.value)   // 乐咕乐股's set just finished: the rows carry it
}
async function checkSw3() {
  try {
    setSw3(await api.marketSw3())
  } catch {
    sw3Timer = window.setTimeout(checkSw3, 10000)
  }
}
// 「下载并同步」: 申万's site refuses programs, so the browser fetches the file (to ~/Downloads)
// and the server, asked every few seconds, copies it in once it lands, when it differs.
const swSyncing = ref(false)
const syncMsg = ref<{ text: string; bad?: boolean } | null>(null)
let syncTimer = 0
function syncSwClass() {
  if (!swc.value || swSyncing.value) return
  const since = Date.now() / 1000 - 5
  window.open(swc.value.url, '_blank')
  swSyncing.value = true
  syncMsg.value = { text: `浏览器下载中，下载完成后自动同步（查找 ${swc.value.downloads} 中的 StockClassifyUse_stock.xls）……` }
  const until = Date.now() + 3 * 60 * 1000
  const poll = async () => {
    try {
      const r = await api.importSwClass(since)
      swc.value = r.status
      if (r.found) {
        swSyncing.value = false
        if (r.changed) {
          const d = r.diff
          syncMsg.value = { text: `已同步申万行业分类（数据截至 ${r.as_of}）${d ? `：新增 ${d.added} 只、剔除 ${d.removed} 只、调整行业 ${d.moved} 只` : ''}` }
          load(date.value)
        } else {
          syncMsg.value = { text: `已检查：申万行业分类（数据截至 ${r.as_of}）与本地一致，无需更新` }
        }
        return
      }
    } catch { /* try again */ }
    if (Date.now() > until) {
      swSyncing.value = false
      syncMsg.value = { bad: true, text: `3 分钟内没在 ${swc.value?.downloads} 找到新下载的 StockClassifyUse_stock.xls：请确认浏览器的下载位置，下载后再点一次按钮` }
      return
    }
    syncTimer = window.setTimeout(poll, 3000)
  }
  syncTimer = window.setTimeout(poll, 3000)
}
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
  if (industry3.value) return all.filter((r) => r.industry3 === industry3.value)
  if (industry2.value) return all.filter((r) => r.sub_industry === industry2.value)
  return industry.value ? all.filter((r) => r.industry === industry.value) : all
})
// The day's count of stocks and of rises, falls and unchanged: the whole market, or the
// chosen industry when one is picked.
const breadth = computed(() => {
  if (!picked3.value && universe.value === 'all' && table.value?.breadth) return table.value.breadth
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
    if (e instanceof ApiError && e.status === 409 && (e.detail as NotSynced)?.code === 'not_synced') {
      loading.value = false
      await needSync(e.detail as NotSynced)
      return
    }
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

// A closed trading day not on disk yet: sync it in the background (today's whole-market
// quote, plus each stock's bars for any day skipped), show the progress, then show the day.
// The newest day on disk stays on screen meanwhile.
const sync = ref<MarketSync | null>(null)
const wanted = ref<string | null>(null)     // the day the sync is for
let pollTimer: number | undefined
const syncing = computed(() => sync.value?.state === 'running')
const syncLine = computed(() => sync.value?.lines.at(-1) || '')

async function needSync(d: NotSynced) {
  wanted.value = d.day
  sync.value = d.sync
  // A sync that failed for these same days waits for 重试 instead of starting over on every visit.
  const failedHere = d.sync.state === 'error' && d.sync.days.join() === d.missing.join()
  if (!failedHere && d.sync.state !== 'running') await startSync()
  else if (d.sync.state === 'running') poll()
  if (!table.value) load(cal.value?.latest || undefined)
}

async function startSync() {
  try {
    sync.value = await api.startMarketSync()
  } catch (e) {
    sync.value = { state: 'error', days: [], msg: e instanceof Error ? e.message : String(e), lines: [], started: null, finished: null }
    return
  }
  if (sync.value.state === 'running') poll()
  else if (sync.value.state === 'ok') done()
}

function poll() {
  window.clearTimeout(pollTimer)
  pollTimer = window.setTimeout(async () => {
    try {
      sync.value = await api.marketSync()
    } catch {
      /* the server may be restarting: try again */
    }
    if (sync.value?.state === 'running') poll()
    else if (sync.value?.state === 'ok') done()
  }, 2000)
}

async function done() {
  cal.value = await api.marketCalendar().catch(() => cal.value)
  const day = wanted.value
  wanted.value = null
  sync.value = null
  if (day) load(day)
}

onBeforeUnmount(() => { window.clearTimeout(pollTimer); window.clearTimeout(sw3Timer); window.clearTimeout(syncTimer) })

// An industry picked under the table: filter the table to it and go back up to it.
function showIndustry(name: string) {
  industry2.value = null
  industry3.value = null
  industry.value = name
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function pick(d: Date | Date[] | (Date | null)[] | null | undefined) {
  if (d instanceof Date && iso(d) !== date.value) load(iso(d))
}

onMounted(async () => {
  if (universe.value === 'hs300') loadHs300()
  checkSw3()
  api.swClass().then((s) => { swc.value = s }).catch(() => {})
  // Open on the latest closed trading day, synced first when it is not on disk yet.
  cal.value = await api.marketCalendar().catch(() => null)
  load(cal.value?.max || undefined)
})
</script>

<template>
  <!-- The table fills one screen; below it the market's stats, and the notes at the very bottom. -->
  <div class="page sides">
    <div class="fill">
      <Message v-if="error" severity="error" class="gap">行情加载失败：{{ error }}</Message>
      <Message v-if="sync && wanted" :severity="sync.state === 'error' ? 'warn' : 'info'" class="gap">
        <div class="row">
          <template v-if="syncing">
            <i class="pi pi-spin pi-spinner" />
            <span>正在同步 {{ (sync.days.length ? sync.days : [wanted]).join('、') }} 的行情（首次补漏掉的交易日需逐只下载，约几分钟），完成后自动显示 {{ wanted }}</span>
            <span v-if="syncLine" class="muted small">{{ syncLine }}</span>
          </template>
          <template v-else-if="sync.state === 'error'">
            <span>{{ wanted }} 的行情同步失败：{{ sync.msg || '未知原因' }}</span>
            <Button label="重试" icon="pi pi-refresh" size="small" text @click="startSync" />
          </template>
        </div>
      </Message>
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
          table-style="table-layout: fixed; min-width: 2276px"
          :global-filter-fields="['code', 'name', 'industry', 'sub_industry', 'industry3']"
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
                  {{ picked3 ? `${picked3} ` : '' }}共 {{ breadth.total }} 只 · <span class="up">涨 {{ breadth.up }}</span> ·
                  <span class="down">跌 {{ breadth.down }}</span> · 平 {{ breadth.flat }}
                </span>
                <span v-if="table?.ttm" class="muted small">TTM：{{ table.ttm }}</span>
              </div>
              <div class="row">
                <Select v-model="industry" :options="industries" placeholder="一级行业" show-clear filter class="industry" />
                <Select v-model="industry2" :options="industries2" placeholder="二级行业" show-clear filter class="industry" />
                <Select v-model="industry3" :options="industries3" :placeholder="sw3Hint" show-clear filter class="industry"
                        :disabled="!industries3.length" :title="sw3Info" />
                <Button :title="`${sw3Info}\n\n点此在浏览器下载申万最新的个股行业分类表，并同步到本地`"
                        :icon="swSyncing ? 'pi pi-spin pi-spinner' : 'pi pi-sync'" severity="secondary" text rounded
                        :disabled="swSyncing || !swc" aria-label="下载并同步申万行业分类" @click="syncSwClass" />
                <span v-if="sw3?.building" class="muted small sw3">三级行业下载中 {{ sw3.done }}/{{ sw3.total || '…' }}</span>
                <IconField>
                  <InputIcon class="pi pi-search" />
                  <InputText v-model="filters.global.value" placeholder="代码、名称或行业" />
                </IconField>
                <Button label="导出 CSV" icon="pi pi-file-export" severity="secondary" outlined @click="dt?.exportCSV()" />
              </div>
            </div>
            <div v-if="syncMsg || (swc && (!swc.ready || swc.due)) || lgCount" class="swnote small">
              <span v-if="syncMsg" :class="syncMsg.bad ? 'warn' : 'muted'">{{ syncMsg.text }}</span>
              <template v-else>
                <span v-if="swc && !swc.ready" class="warn"><i class="pi pi-info-circle" /> 三级行业来自乐咕乐股（非申万官方，可能不全）；点三级行业旁的 <i class="pi pi-sync" /> 下载并同步申万官方分类。</span>
                <span v-else-if="lgCount" class="warn"><i class="pi pi-info-circle" /> {{ lgCount }} 只股票的三级行业来自乐咕乐股（申万官方文件中没有）。</span>
                <span v-if="swc?.ready && swc.due" class="muted">申万行业分类已一个月未检查（数据截至 {{ swc.as_of }}），可点 <i class="pi pi-sync" /> 更新。</span>
              </template>
            </div>
          </template>
          <template #empty><span class="muted">没有匹配的股票</span></template>
          <!-- The row's position as shown, after sorting and filtering: 1, 2, 3 ... from the top. -->
          <Column frozen header="" :exportable="false" header-class="nr" body-class="nr seq" style="width: 60px">
            <template #body="{ index }">{{ index + 1 }}</template>
          </Column>
          <Column frozen header="" :exportable="false" header-class="txt" body-class="txt" style="width: 44px">
            <template #body="{ data }"><WatchStar :code="data.code" /></template>
          </Column>
          <Column frozen field="code" header="代码" sortable header-class="txt" body-class="txt num" style="width: 80px">
            <template #body="{ data }"><span :data-code="data.code">{{ data.code }}</span></template>
          </Column>
          <Column frozen field="name" header="名称" sortable header-class="txt frozen-edge" body-class="txt frozen-edge" style="width: 100px">
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
          <!-- 申万一级 / 二级 / 三级, each sortable; a long name is cut and shown whole on hover. -->
          <Column field="industry" header="一级行业" sortable header-class="txt" body-class="txt ind" style="width: 90px">
            <template #body="{ data }"><span :title="data.industry || ''">{{ data.industry || '—' }}</span></template>
          </Column>
          <Column field="sub_industry" header="二级行业" sortable header-class="txt" body-class="txt ind" style="width: 110px">
            <template #body="{ data }"><span :title="data.sub_industry || ''">{{ data.sub_industry || '—' }}</span></template>
          </Column>
          <Column field="industry3" header="三级行业" sortable header-class="txt" body-class="txt ind" style="width: 140px">
            <template #body="{ data }">
              <span :title="data.industry3 ? `${data.industry3}${data.industry3_src === 'lg' ? '（来自乐咕乐股，非申万官方文件）' : ''}` : ''">{{ data.industry3 || '—' }}<sup v-if="data.industry3_src === 'lg'" class="lg">乐</sup></span>
            </template>
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
      </div>
    </div>
    <MarketStats :rows="table?.rows || []" :date="date" :flow-label="table?.flow.label" :flow-note="table?.flow.note" @industry="showIndustry" />
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
</template>

<style scoped>
/* 序号、星标、代码、名称 stay put while the table scrolls sideways; a line marks where they end. */
.market :deep(.frozen-edge) { box-shadow: inset -1px 0 0 var(--p-datatable-body-cell-border-color, #e2e8f0); }

/* 30px either side of the table (and the stats under it); the usual margin on a phone. */
.sides { padding-left: 30px; padding-right: 30px; }
@media (max-width: 760px) { .sides { padding-left: 12px; padding-right: 12px; } }
.gap { margin-bottom: 12px; }
.fill { height: calc(100vh - 12px); display: flex; flex-direction: column; }
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
.industry { width: 150px; }
.sw3 { white-space: nowrap; font-variant-numeric: tabular-nums; }
:deep(.market td.ind) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lg { color: #b45309; font-size: 10px; margin-left: 1px; }
.swnote { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px 16px; }
.swnote .warn { color: #b45309; }
.note { margin-top: 8px; font-size: 12px; }
.bottom { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--border); }
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
