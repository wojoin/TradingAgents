<script setup lang="ts">
// The day's limit moves: how many closed at the upper and lower limit, how many touched the
// upper limit and fell back (炸板), and the limit-ups by days in a row (连板天梯).
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import SelectButton from 'primevue/selectbutton'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import { api, formatLots, formatPct, formatYuan, upDownClass, type LimitBoard, type LimitStock } from '../api'

const props = defineProps<{ date: string | null }>()
const router = useRouter()
const board = ref<LimitBoard | null>(null)
const loading = ref(false)
const error = ref('')

watch(() => props.date, async (d) => {
  if (!d) return
  loading.value = true
  error.value = ''
  try {
    const b = await api.marketLimits(d)
    if (props.date === d) board.value = b
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}, { immediate: true })

type View = 'up' | 'down' | 'ladder' | 'broken'
const view = ref<View>('up')
const VIEWS = computed(() => [
  { value: 'up', label: `涨停 ${board.value?.limit_up ?? ''}` },
  { value: 'down', label: `跌停 ${board.value?.limit_down ?? ''}` },
  { value: 'ladder', label: '连板天梯' },
  { value: 'broken', label: `炸板 ${board.value?.broken ?? ''}` },
])
// Every limit-up stock, the longest runs first, then by amount traded.
const ups = computed<LimitStock[]>(() =>
  (board.value?.ladder || []).flatMap((step) => step.stocks))
const flat = computed<LimitStock[]>(() => board.value?.broken_list || [])
const downs = computed<LimitStock[]>(() => board.value?.down_list || [])
const noDownTime = computed(() => downs.value.filter((s) => !s.first_time && !s.last_time).length)
// 一级行业-二级行业 for the table (one name when a stock has a single level).
const upRows = computed(() => ups.value.map((s) => ({
  ...s,
  sector: s.industry_l1 && s.industry && s.industry !== s.industry_l1 ? `${s.industry_l1}-${s.industry}` : s.industry || s.industry_l1,
})))
// The limit-up pools leave out some stocks (the Beijing exchange has no 涨停原因).
const noDetail = computed(() => ups.value.filter((s) => !s.first_time && !s.reason).length)
const title = (s: LimitStock) =>
  `${s.code} ${s.name}${s.industry ? ` · ${s.industry}` : ''} · ${s.pct_chg?.toFixed(2) ?? '—'}% · 成交 ${formatYuan(s.amount)}`
const open = (s: LimitStock) => router.push(`/stock/${s.code}`)
</script>

<template>
  <section class="card wide">
    <div class="head">
      <h3>涨停板</h3>
      <span class="muted small">{{ board?.date || date }}</span>
    </div>
    <p v-if="error" class="bad small">{{ error }}</p>
    <p v-else-if="loading && !board" class="muted small"><i class="pi pi-spin pi-spinner" /> 统计中</p>
    <template v-if="board">
      <div class="figures">
        <div><span class="muted">涨停</span><b class="up">{{ board.limit_up }}</b></div>
        <div><span class="muted">跌停</span><b class="down">{{ board.limit_down }}</b></div>
        <div><span class="muted">炸板</span><b>{{ board.broken }}</b></div>
        <div><span class="muted">炸板率</span><b>{{ board.broken_rate === null ? '—' : `${board.broken_rate.toFixed(1)}%` }}</b></div>
        <div><span class="muted">最高连板</span><b class="up">{{ board.max_streak ? `${board.max_streak} 板` : '—' }}</b></div>
      </div>
      <p class="muted small">炸板：盘中触及涨停、收盘未封住；炸板率 = 炸板 ÷（涨停 + 炸板）。连板按连续收盘涨停的交易日计；行业为申万二级。</p>
      <SelectButton v-model="view" :options="VIEWS" option-label="label" option-value="value" :allow-empty="false" size="small" />
      <div v-if="view === 'ladder'" class="ladder">
        <p v-if="!board.ladder.length" class="muted small">当日没有涨停</p>
        <div v-for="step in board.ladder" :key="step.streak" class="step">
          <span class="height" :class="{ hot: step.streak >= 2 }">{{ step.streak === 1 ? '首板' : `${step.streak} 连板` }}
            <span class="muted">{{ step.stocks.length }}</span></span>
          <span class="chips">
            <a v-for="s in step.stocks" :key="s.code" class="chip" :title="title(s)" @click="open(s)">
              {{ s.name }}<span v-if="s.industry" class="muted"> · {{ s.industry }}</span>
            </a>
          </span>
        </div>
      </div>
      <template v-else-if="view === 'up'">
        <DataTable :value="upRows" data-key="code" scrollable scroll-height="420px" size="small" striped-rows
                   removable-sort class="zt">
          <template #empty><span class="muted small">当日没有涨停</span></template>
          <Column field="name" header="名字" sortable frozen header-class="edge" body-class="edge name" style="width: 1%">
            <template #body="{ data }">
              <div class="nm">
                <a class="link" @click="open(data)">{{ data.name }}</a>
                <b v-if="data.streak" class="board" :class="data.streak >= 2 ? 'up' : 'first'">{{ data.streak >= 2 ? `${data.streak}板` : '首板' }}</b>
                <div class="code">{{ data.code }}</div>
              </div>
            </template>
          </Column>
          <Column field="pct_chg" header="涨幅" sortable header-class="nr" body-class="nr">
            <template #body="{ data }"><span :class="upDownClass(data.pct_chg)">{{ formatPct(data.pct_chg) }}</span></template>
          </Column>
          <Column field="close" header="最新" sortable header-class="nr" body-class="nr">
            <template #body="{ data }"><span :class="upDownClass(data.pct_chg)">{{ data.close?.toFixed(2) ?? '—' }}</span></template>
          </Column>
          <Column field="sector" header="行业" sortable body-class="nowrap">
            <template #body="{ data }">{{ data.sector || '—' }}</template>
          </Column>
          <Column field="reason" header="涨停原因" style="min-width: 180px; max-width: 260px">
            <template #body="{ data }"><span class="reason">{{ data.reason || '—' }}</span></template>
          </Column>
          <Column field="first_time" header="首次涨停时间" sortable header-class="nr" body-class="nr">
            <template #body="{ data }">{{ data.first_time || '—' }}</template>
          </Column>
          <Column field="last_time" header="最后涨停时间" sortable header-class="nr" body-class="nr">
            <template #body="{ data }">{{ data.last_time || '—' }}</template>
          </Column>
          <Column field="shape" header="涨停形态" sortable>
            <template #body="{ data }">
              <span v-if="data.shape" class="shape" :class="{ yz: data.shape === '一字板', tz: data.shape === 'T字板' }">{{ data.shape }}</span>
              <span v-else>—</span>
            </template>
          </Column>
          <Column field="order_volume" header="封单量" sortable header-class="nr" body-class="nr">
            <template #body="{ data }">{{ data.order_volume == null ? '—' : formatLots(data.order_volume / 100) }}</template>
          </Column>
          <Column field="order_amount" header="封单额" sortable header-class="nr" body-class="nr">
            <template #body="{ data }">{{ formatYuan(data.order_amount) }}</template>
          </Column>
          <Column field="turnover" header="换手率" sortable header-class="nr" body-class="nr">
            <template #body="{ data }">{{ data.turnover == null ? '—' : `${data.turnover.toFixed(2)}%` }}</template>
          </Column>
        </DataTable>
        <p class="muted small note">涨停原因、涨停时间和封单来自同花顺涨停池（北交所取自东方财富，无涨停原因），封单为收盘时的数；
          形态按当日开盘、最低价判断：一字板全天封住，T字板开盘封住、盘中开板后回封，其余为换手板。<template v-if="noDetail">
          {{ noDetail }} 只涨停池里没有，显示为 —。</template></p>
      </template>
      <template v-else-if="view === 'down'">
        <DataTable :value="downs" data-key="code" scrollable scroll-height="420px" size="small" striped-rows
                   removable-sort class="zt">
          <template #empty><span class="muted small">当日没有跌停</span></template>
          <Column field="name" header="名字" sortable frozen header-class="edge" body-class="edge name" style="width: 1%">
            <template #body="{ data }">
              <div class="nm">
                <a class="link" @click="open(data)">{{ data.name }}</a>
                <div class="code">{{ data.code }}</div>
              </div>
            </template>
          </Column>
          <Column field="pct_chg" header="跌幅" sortable header-class="nr" body-class="nr">
            <template #body="{ data }"><span :class="upDownClass(data.pct_chg)">{{ formatPct(data.pct_chg) }}</span></template>
          </Column>
          <Column field="close" header="最新" sortable header-class="nr" body-class="nr">
            <template #body="{ data }"><span :class="upDownClass(data.pct_chg)">{{ data.close?.toFixed(2) ?? '—' }}</span></template>
          </Column>
          <Column field="first_time" header="首次跌停时间" sortable header-class="nr" body-class="nr">
            <template #body="{ data }">{{ data.first_time || '—' }}</template>
          </Column>
          <Column field="last_time" header="最后跌停时间" sortable header-class="nr" body-class="nr">
            <template #body="{ data }">{{ data.last_time || '—' }}</template>
          </Column>
          <Column field="turnover" header="换手率" sortable header-class="nr" body-class="nr">
            <template #body="{ data }">{{ data.turnover == null ? '—' : `${data.turnover.toFixed(2)}%` }}</template>
          </Column>
        </DataTable>
        <p class="muted small note">跌停时间来自同花顺跌停池（北交所取自东方财富，只有最后跌停时间）。<template v-if="noDownTime">
          {{ noDownTime }} 只跌停池里没有，显示为 —。</template></p>
      </template>
      <div v-else class="chips flat">
        <p v-if="!flat.length" class="muted small">没有</p>
        <a v-for="s in flat" :key="s.code" class="chip" :title="title(s)" @click="open(s)">
          {{ s.name }} <span :class="(s.pct_chg ?? 0) >= 0 ? 'up' : 'down'">{{ s.pct_chg?.toFixed(2) }}%</span>
          <b v-if="(s.streak ?? 0) >= 2" class="up"> {{ s.streak }}板</b>
          <span v-if="s.industry" class="muted"> · {{ s.industry }}</span>
        </a>
      </div>
    </template>
  </section>
</template>

<style scoped>
.wide { grid-column: 1 / -1; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h3 { margin: 0; font-size: 15px; }
.small { font-size: 12px; }
.bad { color: var(--up); }
.figures { display: flex; flex-wrap: wrap; gap: 28px; margin: 10px 0 2px; font-variant-numeric: tabular-nums; }
.figures div { display: flex; flex-direction: column; gap: 2px; font-size: 12px; }
.figures b { font-size: 20px; }
.ladder { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; max-height: 360px; overflow-y: auto; }
.step { display: grid; grid-template-columns: 84px 1fr; gap: 8px; align-items: start; }
.height { font-weight: 600; font-size: 13px; padding-top: 3px; }
.height.hot { color: var(--up); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chips.flat { margin-top: 10px; max-height: 300px; overflow-y: auto; }
.chip { font-size: 12px; padding: 3px 8px; border: 1px solid var(--border); border-radius: 12px; cursor: pointer; white-space: nowrap; }
.chip:hover { border-color: var(--up); }
.zt { margin-top: 10px; }
.link { cursor: pointer; font-weight: 500; }
.link:hover { color: var(--up); }
.code { font-size: 11px; color: var(--muted); margin-top: 1px; }
.reason { white-space: normal; line-height: 1.35; }
.shape { font-size: 12px; padding: 1px 6px; border-radius: 4px; border: 1px solid var(--border); white-space: nowrap; }
.shape.yz { color: #fff; background: var(--up); border-color: var(--up); }
.shape.tz { color: var(--up); border-color: var(--up); }
.note { margin: 6px 0 0; }
:deep(.zt th.nr), :deep(.zt td.nr) { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
:deep(.zt th.nr .p-datatable-column-header-content) { justify-content: flex-end; }
:deep(.zt th) { white-space: nowrap; }
:deep(.zt td.name), :deep(.zt td.nowrap) { white-space: nowrap; }
/* Room for a four-character name and its board tag (about 6em), plus a fifth. */
.nm { min-width: 7.2em; }
.board { font-size: 12px; margin-left: 4px; }
.board.first { color: var(--up); font-weight: 500; opacity: 0.75; }
:deep(.zt .edge) { box-shadow: inset -1px 0 0 var(--p-datatable-body-cell-border-color, #e2e8f0); }
</style>
