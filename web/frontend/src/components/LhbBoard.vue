<script setup lang="ts">
// 龙虎榜: the stocks on the exchanges' list for the day (Eastmoney), with what the listed seats
// bought and sold and the institutions' share of it.
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import { api, formatLots, formatPct, formatYuan, upDownClass, type LhbSeats, type MarketLhb } from '../api'

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
// The seats of a row, fetched when it is opened.
const expanded = ref<Record<string, boolean>>({})
const seats = ref<Record<string, LhbSeats | { error: string } | undefined>>({})
watch(() => props.date, () => { expanded.value = {}; seats.value = {} })
async function openRow(e: { data: { code: string } }) {
  const code = e.data.code
  if (seats.value[code]) return
  try {
    seats.value = { ...seats.value, [code]: await api.marketLhbSeats(code, data.value?.date || props.date || undefined) }
  } catch (err) {
    seats.value = { ...seats.value, [code]: { error: err instanceof Error ? err.message : String(err) } }
  }
}
const seatsOf = (code: string) => seats.value[code]
const pctText = (v: number | null) => (v === null ? '' : `${v.toFixed(2)}%`)
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
      <b>机构大额净买</b>多被视为认可，<b>游资席位集中买入</b>多为短线炒作；席位净买占成交越高，席位影响越大。<br>
      <b>席位净买</b> = 上榜席位（买入、卖出各前 5，同一席位只计一次）的买入额 − 卖出额；<b>席位净买占成交</b> = 席位净买 ÷ 上榜统计期间该股总成交额；
      <b>机构净买</b> = 其中机构专用席位的净买，是席位净买的一部分。因「连续三个交易日」上榜的，席位金额与占比均为 3 日合计，而成交额、成交量列为当日。</p>
    <p v-if="data?.available" class="muted small sub">点每行开头的 <i class="pi pi-chevron-right small" /> 展开该股买入、卖出金额最大的前 5 个席位。</p>
    <DataTable v-if="data?.available" v-model:expanded-rows="expanded" :value="data.stocks" data-key="code" scrollable scroll-height="560px"
               size="small" striped-rows removable-sort class="lhb" @row-expand="openRow">
      <Column expander style="width: 2.5rem" />
      <Column field="name" header="名字" sortable header-class="edge" body-class="edge" style="width: 1%">
        <template #body="{ data: s }">
          <div class="nm"><a class="link" @click="router.push(`/stock/${s.code}`)">{{ s.name }}</a>
            <div class="code">{{ s.code }}</div></div>
        </template>
      </Column>
      <Column field="pct" header="涨跌幅" sortable header-class="nr" body-class="nr">
        <template #body="{ data: s }"><span :class="upDownClass(s.pct)">{{ formatPct(s.pct) }}</span></template>
      </Column>
      <Column field="close" header="最新" sortable header-class="nr" body-class="nr">
        <template #body="{ data: s }"><span :class="upDownClass(s.pct)">{{ s.close?.toFixed(2) ?? '—' }}</span></template>
      </Column>
      <Column field="amount" header="成交额" sortable header-class="nr" body-class="nr">
        <template #body="{ data: s }">{{ formatYuan(s.amount) }}</template>
      </Column>
      <Column field="volume" header="成交量" sortable header-class="nr" body-class="nr">
        <template #body="{ data: s }">{{ formatLots(s.volume) }}</template>
      </Column>
      <Column field="buy" header="买入额" sortable header-class="nr" body-class="nr">
        <template #body="{ data: s }"><span class="up">{{ formatYuan(s.buy) }}</span></template>
      </Column>
      <Column field="sell" header="卖出额" sortable header-class="nr" body-class="nr">
        <template #body="{ data: s }"><span class="down">{{ formatYuan(s.sell) }}</span></template>
      </Column>
      <Column field="net" header="席位净买" sortable header-class="nr" body-class="nr">
        <template #body="{ data: s }"><span :class="upDownClass(s.net)">{{ yi(s.net) }}</span></template>
      </Column>
      <Column field="net_share" header="席位净买占成交" sortable header-class="nr" body-class="nr">
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
      <template #expansion="{ data: s }">
        <div class="seats">
          <p v-if="!seatsOf(s.code)" class="muted small"><i class="pi pi-spin pi-spinner" /> 获取席位明细</p>
          <p v-else-if="'error' in seatsOf(s.code)!" class="bad small">{{ (seatsOf(s.code) as { error: string }).error }}</p>
          <p v-else-if="!(seatsOf(s.code) as LhbSeats).available" class="muted small">{{ (seatsOf(s.code) as LhbSeats).note }}</p>
          <template v-else>
            <div v-for="g in (seatsOf(s.code) as LhbSeats).groups" :key="g.reason" class="group">
              <div class="gsum">
                <span class="muted">{{ g.reason }}</span>
                <span>上榜席位买入 <b class="up">{{ formatYuan(g.top_buy) }}</b> · 卖出 <b class="down">{{ formatYuan(g.top_sell) }}</b> ·
                  净额 <b :class="upDownClass(g.top_net)">{{ yi(g.top_net) }}</b>
                  <template v-if="g.inst_net !== null"> · 机构净买 <b :class="upDownClass(g.inst_net)">{{ yi(g.inst_net) }}</b></template></span>
              </div>
              <div class="sides">
                <table v-for="side in (['buy', 'sell'] as const)" :key="side" class="seat">
                  <thead>
                    <tr>
                      <th :class="side === 'buy' ? 'up' : 'down'">{{ side === 'buy' ? '买入前5' : '卖出前5' }}</th>
                      <!-- Each side's own amount first: 买入 on the buying side, 卖出 on the selling side. -->
                      <template v-if="side === 'buy'"><th class="nr">买入</th><th class="nr">卖出</th></template>
                      <template v-else><th class="nr">卖出</th><th class="nr">买入</th></template>
                      <th class="nr">净额</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(x, i) in g[side]" :key="i">
                      <td class="sname"><span class="kind" :class="x.kind === '机构' ? 'inst' : x.kind === '北向' ? 'north' : ''">{{ x.kind }}</span>{{ x.seat }}</td>
                      <template v-if="side === 'buy'">
                        <td class="nr" :title="pctText(x.buy_share)">{{ formatYuan(x.buy) }}</td>
                        <td class="nr" :title="pctText(x.sell_share)">{{ formatYuan(x.sell) }}</td>
                      </template>
                      <template v-else>
                        <td class="nr" :title="pctText(x.sell_share)">{{ formatYuan(x.sell) }}</td>
                        <td class="nr" :title="pctText(x.buy_share)">{{ formatYuan(x.buy) }}</td>
                      </template>
                      <td class="nr" :class="upDownClass(x.net)">{{ yi(x.net) }}</td>
                    </tr>
                    <tr v-if="!g[side].length"><td colspan="4" class="muted">—</td></tr>
                  </tbody>
                </table>
              </div>
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
.seats { padding: 6px 4px 10px 36px; }
.group + .group { margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--border); }
.gsum { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 16px; font-size: 12px; margin-bottom: 6px; font-variant-numeric: tabular-nums; }
.sides { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 1100px) { .sides { grid-template-columns: 1fr; } }
.seat { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
.seat th { text-align: left; font-weight: 600; padding: 3px 6px; border-bottom: 1px solid var(--border); white-space: nowrap; }
.seat td { padding: 3px 6px; border-bottom: 1px solid #f1f3f6; white-space: nowrap; }
.seat .nr { text-align: right; }
.sname { max-width: 340px; overflow: hidden; text-overflow: ellipsis; }
.kind { display: inline-block; font-size: 11px; padding: 0 5px; margin-right: 6px; border-radius: 4px; background: #f1f3f6; color: var(--muted); }
.kind.inst { background: #fff1e6; color: #c2410c; }
.kind.north { background: #e0ecff; color: #1d4ed8; }
:deep(.lhb .edge) { box-shadow: inset -1px 0 0 var(--p-datatable-body-cell-border-color, #e2e8f0); white-space: nowrap; }
</style>
