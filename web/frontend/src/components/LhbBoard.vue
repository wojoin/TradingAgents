<script setup lang="ts">
// 龙虎榜: the stocks on the exchanges' list for the day (Eastmoney), with what the listed seats
// bought and sold and the institutions' share of it.
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import { api, formatPct, formatYuan, upDownClass, type MarketLhb } from '../api'

const props = defineProps<{ date: string | null }>()
const router = useRouter()
const data = ref<MarketLhb | null>(null)
const error = ref('')
const loading = ref(false)
watch(() => props.date, async (d) => {
  if (!d) return
  loading.value = true
  error.value = ''
  try {
    const x = await api.marketLhb(d)
    if (props.date === d) data.value = x
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}, { immediate: true })
const yi = (v: number | null | undefined) => (v === null || v === undefined ? '—' : formatYuan(v, true))
</script>

<template>
  <section class="card wide">
    <div class="head">
      <h3>龙虎榜</h3>
      <span class="muted small">{{ data?.date || date }}</span>
    </div>
    <p v-if="error" class="bad small">{{ error }}</p>
    <p v-else-if="loading && !data" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <p v-else-if="data && !data.available" class="muted small">{{ data.note }}</p>
    <p v-else-if="data" class="sum">
      上榜 <b>{{ data.count }}</b> 只，龙虎榜席位合计净买 <b :class="upDownClass(data.net)">{{ yi(data.net) }}</b>；
      机构参与 {{ data.inst_count }} 只，机构合计净买 <b :class="upDownClass(data.inst_net)">{{ yi(data.inst_net) }}</b>
    </p>
    <p class="muted small sub">交易所公布的异动股票（涨跌幅偏离、换手率高等）及买卖金额最大的营业部席位，收盘后约 18:00 公布。
      <b>机构大额净买</b>多被视为认可，<b>游资席位集中买入</b>多为短线炒作；净买额占成交比越高，席位影响越大。</p>
    <DataTable v-if="data?.available" :value="data.stocks" data-key="code" scrollable scroll-height="420px"
               size="small" striped-rows removable-sort class="lhb">
      <Column field="name" header="名字" sortable frozen header-class="edge" body-class="edge" style="width: 1%">
        <template #body="{ data: s }">
          <div class="nm"><a class="link" @click="router.push(`/stock/${s.code}`)">{{ s.name }}</a>
            <div class="code">{{ s.code }}</div></div>
        </template>
      </Column>
      <Column field="pct" header="涨跌幅" sortable header-class="nr" body-class="nr">
        <template #body="{ data: s }"><span :class="upDownClass(s.pct)">{{ formatPct(s.pct) }}</span></template>
      </Column>
      <Column field="net" header="席位净买" sortable header-class="nr" body-class="nr">
        <template #body="{ data: s }"><span :class="upDownClass(s.net)">{{ yi(s.net) }}</span></template>
      </Column>
      <Column field="net_share" header="净买占成交" sortable header-class="nr" body-class="nr">
        <template #body="{ data: s }">{{ s.net_share === null ? '—' : `${s.net_share.toFixed(1)}%` }}</template>
      </Column>
      <Column field="inst_net" header="机构净买" sortable header-class="nr" body-class="nr">
        <template #body="{ data: s }"><span :class="upDownClass(s.inst_net)">{{ yi(s.inst_net) }}</span>
          <span v-if="s.inst_buyers !== null" class="muted small"> {{ s.inst_buyers }}买{{ s.inst_sellers }}卖</span></template>
      </Column>
      <Column field="turnover" header="换手率" sortable header-class="nr" body-class="nr">
        <template #body="{ data: s }">{{ s.turnover === null ? '—' : `${s.turnover.toFixed(2)}%` }}</template>
      </Column>
      <Column field="note" header="解读" style="min-width: 150px">
        <template #body="{ data: s }"><span class="muted">{{ s.note }}</span></template>
      </Column>
      <Column field="reason" header="上榜原因" style="min-width: 260px">
        <template #body="{ data: s }"><span class="reason">{{ s.reason }}</span></template>
      </Column>
    </DataTable>
  </section>
</template>

<style scoped>
.wide { grid-column: 1 / -1; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h3 { margin: 0; font-size: 15px; }
.sum { margin: 8px 0; font-size: 13px; line-height: 1.6; font-variant-numeric: tabular-nums; }
.small { font-size: 12px; }
.sub { margin: 6px 0; }
.bad { color: var(--up); }
.link { cursor: pointer; font-weight: 500; }
.link:hover { color: var(--up); }
.nm { min-width: 6em; }
.code { font-size: 11px; color: var(--muted); }
.reason { white-space: normal; font-size: 12px; line-height: 1.4; }
:deep(.lhb th.nr), :deep(.lhb td.nr) { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
:deep(.lhb th.nr .p-datatable-column-header-content) { justify-content: flex-end; }
:deep(.lhb th) { white-space: nowrap; }
:deep(.lhb .edge) { box-shadow: inset -1px 0 0 var(--p-datatable-body-cell-border-color, #e2e8f0); white-space: nowrap; }
</style>
