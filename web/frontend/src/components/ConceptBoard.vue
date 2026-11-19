<script setup lang="ts">
// 概念板块热度: 同花顺's concept boards on the day or over 5 / 10 days, their change and money
// flow (同花顺's measure), sortable. 同花顺 keeps no history: the latest closed day only.
import { computed, ref, watch } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import SelectButton from 'primevue/selectbutton'
import { useRouter } from 'vue-router'
import { api, formatYuan, upDownClass, type ConceptStocks, type FlowSpan, type MarketConcepts } from '../api'

const props = defineProps<{ date: string | null }>()

function stored(key: string, fallback: FlowSpan): ReturnType<typeof ref<FlowSpan>> {
  let v = fallback
  try {
    const s = localStorage.getItem(key)
    if (s === '1d' || s === '5d' || s === '10d') v = s
  } catch {
    /* storage blocked: the default */
  }
  const r = ref<FlowSpan>(v)
  watch(r, (x) => {
    try {
      localStorage.setItem(key, x as string)
    } catch {
      /* storage blocked */
    }
  })
  return r
}
const span = stored('market.conceptSpan', '1d')
const SPANS = [{ value: '1d', label: '当日' }, { value: '5d', label: '5日' }, { value: '10d', label: '10日' }]
const data = ref<MarketConcepts | null>(null)
const error = ref('')
const loading = ref(false)
watch([span, () => props.date], async ([sp, d]) => {
  if (!d || !sp) return
  loading.value = true
  error.value = ''
  try {
    const r = await api.marketConcepts(sp, d)
    if (span.value === sp && props.date === d) data.value = r
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}, { immediate: true })
// A concept's stocks, fetched when its row is opened (kept locally on the server, checked monthly).
const router = useRouter()
const expanded = ref<Record<string, boolean>>({})
const members = ref<Record<string, ConceptStocks | { error: string } | undefined>>({})
watch(() => props.date, () => { expanded.value = {}; members.value = {} })
async function openRow(e: { data: { name: string } }) {
  const name = e.data.name
  if (members.value[name]) return
  try {
    members.value = { ...members.value, [name]: await api.marketConceptStocks(name, props.date || undefined) }
  } catch (err) {
    members.value = { ...members.value, [name]: { error: err instanceof Error ? err.message : String(err) } }
  }
}
const got = (name: string) => members.value[name]
const SOURCE: Record<string, string> = { cache: '本地缓存', network: '刚从网络更新', stale: '网络暂不可用，使用本地缓存' }
const top = computed(() => (data.value?.concepts || []).slice(0, 5).map((c) => c.name))
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)
</script>

<template>
  <section class="card wide">
    <div class="head">
      <h3>概念板块热度</h3>
      <SelectButton v-model="span" :options="SPANS" option-label="label" option-value="value" :allow-empty="false" size="small" />
    </div>
    <p v-if="error" class="bad small">{{ error }}</p>
    <p v-else-if="loading && !data" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p v-else-if="data && !data.available" class="muted small">{{ data.note }}</p>
    <p v-else-if="data" class="sum">
      {{ data.date }}：{{ data.count }} 个概念中 <b class="up">{{ data.up }}</b> 个上涨；涨幅居前：<b>{{ top.join('、') }}</b>
    </p>
    <p class="muted small sub">同花顺概念板块的涨跌幅与资金流，可按任一列排序。与「主线题材」互相印证：<b>涨幅居前且资金净流入</b>的概念是当下热点；
      资金为同花顺口径（按主动买卖方向统计全部成交，不分主力）。同花顺只提供最近一个交易日的数据。</p>
    <p v-if="data?.available" class="muted small sub">点每行开头的 <i class="pi pi-chevron-right small" /> 展开该概念的成分股（依次取东方财富、同花顺、新浪的同名概念板块；本地缓存、每月检查更新）。</p>
    <DataTable v-if="data?.available" v-model:expanded-rows="expanded" :value="data.concepts" data-key="name" scrollable scroll-height="520px"
               size="small" striped-rows removable-sort class="cpt" @row-expand="openRow">
      <Column expander style="width: 2.5rem" />
      <Column field="name" header="概念" sortable style="min-width: 120px" />
      <Column field="pct" header="涨跌幅" sortable header-class="nr" body-class="nr">
        <template #body="{ data: c }"><span :class="upDownClass(c.pct)">{{ pct(c.pct) }}</span></template>
      </Column>
      <Column field="net" header="资金净额" sortable header-class="nr" body-class="nr">
        <template #body="{ data: c }"><span :class="upDownClass(c.net)">{{ formatYuan(c.net, true) }}</span></template>
      </Column>
      <Column field="inflow" header="流入" sortable header-class="nr" body-class="nr">
        <template #body="{ data: c }">{{ formatYuan(c.inflow) }}</template>
      </Column>
      <Column field="outflow" header="流出" sortable header-class="nr" body-class="nr">
        <template #body="{ data: c }">{{ formatYuan(c.outflow) }}</template>
      </Column>
      <Column field="count" header="家数" sortable header-class="nr" body-class="nr" />
      <Column v-if="span === '1d'" field="leader" header="领涨股">
        <template #body="{ data: c }"><template v-if="c.leader">{{ c.leader }} <span :class="upDownClass(c.leader_pct)">{{ pct(c.leader_pct) }}</span></template><span v-else>—</span></template>
      </Column>
      <template #expansion="{ data: c }">
        <div class="members">
          <p v-if="!got(c.name)" class="muted small"><i class="pi pi-spin pi-spinner" /> 获取成分股</p>
          <p v-else-if="'error' in got(c.name)!" class="bad small">{{ (got(c.name) as { error: string }).error }}</p>
          <div v-else-if="!(got(c.name) as ConceptStocks).available" class="small">
            <template v-if="(got(c.name) as ConceptStocks).tried">
              <div class="bad">成分股暂不可得，以下来源依次尝试均不可用：</div>
              <ol class="tried">
                <li v-for="t in (got(c.name) as ConceptStocks).tried" :key="t.source"><b>{{ t.source }}</b>：<span class="muted">{{ t.error }}</span></li>
              </ol>
            </template>
            <span v-else class="muted">{{ (got(c.name) as ConceptStocks).note }}</span>
          </div>
          <template v-else>
            <p v-if="(got(c.name) as ConceptStocks).provider === 'sina'" class="small warn">
              <i class="pi pi-info-circle" /> {{ (got(c.name) as ConceptStocks).provider_note }}，改用新浪「{{ (got(c.name) as ConceptStocks).em_name }}」的成分股，与同花顺的口径可能略有不同。
            </p>
            <div class="msum small">
              <span>
                <template v-if="(got(c.name) as ConceptStocks).matched === 'loose' && (got(c.name) as ConceptStocks).provider !== 'sina'">东方财富「{{ (got(c.name) as ConceptStocks).em_name }}」· </template>
                {{ (got(c.name) as ConceptStocks).count }} 只：<span class="up">涨 {{ (got(c.name) as ConceptStocks).up }}</span> ·
                <span class="down">跌 {{ (got(c.name) as ConceptStocks).down }}</span> · 中位
                <span :class="upDownClass((got(c.name) as ConceptStocks).median)">{{ pct((got(c.name) as ConceptStocks).median) }}</span>
              </span>
              <span class="muted" :class="{ warn: (got(c.name) as ConceptStocks).source === 'stale' }">
                {{ SOURCE[(got(c.name) as ConceptStocks).source!] }}，成分股检查于 {{ (got(c.name) as ConceptStocks).checked }}
              </span>
            </div>
            <p v-if="(got(c.name) as ConceptStocks).last_change" class="small change">
              {{ (got(c.name) as ConceptStocks).last_change!.date }} 成分股变动：
              <template v-if="(got(c.name) as ConceptStocks).last_change!.added.length">新增 <b class="up">{{ (got(c.name) as ConceptStocks).last_change!.added.map((x) => x.name).join('、') }}</b></template>
              <template v-if="(got(c.name) as ConceptStocks).last_change!.removed.length">；剔除 <b class="down">{{ (got(c.name) as ConceptStocks).last_change!.removed.map((x) => x.name).join('、') }}</b></template>
            </p>
            <div class="mwrap">
              <table class="mtable">
                <thead><tr><th>股票</th><th class="nr">涨跌幅</th><th class="nr">最新</th><th class="nr">成交额</th><th>行业</th></tr></thead>
                <tbody>
                  <tr v-for="m in (got(c.name) as ConceptStocks).stocks" :key="m.code">
                    <td><a class="link" @click="router.push(`/stock/${m.code}`)">{{ m.name }}</a> <span class="muted code">{{ m.code }}</span></td>
                    <td class="nr" :class="upDownClass(m.pct)">{{ pct(m.pct) }}</td>
                    <td class="nr" :class="upDownClass(m.pct)">{{ m.close?.toFixed(2) ?? '—' }}</td>
                    <td class="nr">{{ formatYuan(m.amount) }}</td>
                    <td class="muted">{{ m.industry || '' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
        </div>
      </template>
    </DataTable>
  </section>
</template>

<style scoped>
.wide { grid-column: 1 / -1; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h3 { margin: 0; font-size: 15px; }
.sum { margin: 8px 0; font-size: 13px; line-height: 1.6; }
.small { font-size: 12px; }
.sub { margin: 6px 0; }
.bad { color: var(--up); }
:deep(.cpt th.nr), :deep(.cpt td.nr) { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
:deep(.cpt th.nr .p-datatable-column-header-content) { justify-content: flex-end; }
:deep(.cpt td) { white-space: nowrap; }
.members { padding: 6px 4px 10px 36px; }
.msum { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 16px; margin-bottom: 4px; font-variant-numeric: tabular-nums; }
.change { margin: 2px 0 6px; }
.tried { margin: 4px 0 0; padding-left: 20px; line-height: 1.7; }
.warn { color: #b45309; }
.mwrap { max-height: 300px; overflow-y: auto; }
.mtable { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
.mtable th { text-align: left; font-weight: 500; color: var(--muted); padding: 3px 6px; border-bottom: 1px solid var(--border); position: sticky; top: 0; background: #fff; }
.mtable td { padding: 3px 6px; border-bottom: 1px solid #f1f3f6; white-space: nowrap; }
.mtable .nr { text-align: right; }
.code { font-size: 11px; }
.link { cursor: pointer; }
.link:hover { color: var(--up); }
</style>
