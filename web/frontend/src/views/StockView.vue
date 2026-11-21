<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import Message from 'primevue/message'
import Tag from 'primevue/tag'
import { useToast } from 'primevue/usetoast'
import { api, formatLots, formatPct, formatYuan, upDownClass, type Quote } from '../api'
import KlineChart from '../components/KlineChart.vue'
import StockPicker from '../components/StockPicker.vue'
import { periodKey, type KlineHover } from '../kperiod'
import WatchStar from '../components/WatchStar.vue'

// One stock: its latest quote, daily K-line and saved reports, and a button to analyse it.
const props = defineProps<{ code?: string }>()
const router = useRouter()
const toast = useToast()
const quote = ref<Quote | null>(null)
const error = ref('')

async function load() {
  quote.value = null
  error.value = ''
  if (!props.code) return
  try {
    quote.value = await api.quote(props.code)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

// The main-force net inflow by day (Eastmoney keeps about 120 trading days; the server keeps more).
const flows = ref<{ since: string | null; note: string | null; days: Record<string, number> } | null>(null)
async function loadFlows() {
  flows.value = null
  if (!props.code) return
  try {
    flows.value = await api.stockFlow(props.code)
  } catch {
    flows.value = null       // not an A-share, or nothing kept: the card shows —
  }
}
// The bar's flow: the day's, or the week's / month's days added up (— when any day is missing).
function barFlow(h: KlineHover): number | null {
  const days = flows.value?.days
  if (!days) return null
  if (h.period === 'day') return days[h.bar.time] ?? null
  const key = periodKey(h.bar.time, h.period)
  const inside = Object.keys(days).filter((d) => periodKey(d, h.period) === key)
  if (!inside.length || !flows.value?.since || flows.value.since > h.bar.time) return null
  return inside.reduce((a, d) => a + days[d], 0)
}

// The K-line bar under the mouse: the card shows that day (or week, month) instead of the latest.
const hover = ref<KlineHover | null>(null)
const onBar = computed(() => (hover.value && !hover.value.latest ? hover.value : null))
// What the card shows: the bar under the mouse, else the latest quote (with the last bar's open,
// high and low, which the quote does not carry).
const card = computed(() => {
  const q = quote.value
  const h = onBar.value
  const last = hover.value?.bar
  if (h?.minute) {                          // 分时 / 五日: the minute under the mouse
    const m = h.minute
    return {
      date: `${m.date} ${m.time}`, history: true, minute: true, open: h.bar.open, high: h.bar.high, low: h.bar.low,
      price: m.price, pct: h.change, avg: m.avg, amount: m.amount, volume: m.volume / 100, turnover: null as number | null,
      flow: null as number | null, total_mv: q?.total_mv && q.price ? (q.total_mv / q.price) * m.price : null,
    }
  }
  if (h) {
    const b = h.bar
    const shares = q?.total_mv && q.price ? q.total_mv / q.price : null
    return {
      date: `${b.time}${h.period === 'week' ? ' 周' : h.period === 'month' ? ' 月' : ''}`, history: true, minute: false, avg: null as number | null,
      open: b.open, high: b.high, low: b.low, price: b.close, pct: h.change,
      amount: b.amount ?? null, volume: b.volume, turnover: b.turnover ?? null,
      flow: barFlow(h), total_mv: shares ? shares * b.close : null,
    }
  }
  if (!q) return null
  const sameDay = last && last.time === q.date
  return {
    date: q.date, history: false, minute: false, avg: null as number | null, open: sameDay ? last.open : null, high: sameDay ? last.high : null,
    low: sameDay ? last.low : null, price: q.price, pct: q.pct_chg, amount: q.amount, volume: q.volume,
    turnover: q.turnover, flow: q.main_flow, total_mv: q.total_mv,
  }
})

async function pick(value: string) {
  // A name resolves through search; a code (or a foreign ticker) goes straight in.
  if (/^[A-Za-z0-9.\-^=]{1,20}$/.test(value)) return router.push(`/stock/${value}`)
  const hits = await api.search(value, 2).catch(() => [])
  if (hits.length) router.push(`/stock/${hits[0].code}`)
  else toast.add({ severity: 'warn', summary: '找不到股票', detail: value, life: 4000 })
}

// Analysing opens the analysis form with this stock filled in, to choose the options first.
function analyse() {
  if (props.code) router.push({ path: '/analysis', query: { ticker: props.code } })
}

watch(() => props.code, () => {
  hover.value = null
  load()
  loadFlows()
}, { immediate: true })
</script>

<template>
  <div class="page">
    <!-- One compact card above the chart, so the chart and its three panes fit the screen. -->
    <div class="card head">
      <div class="row between">
        <div class="row">
          <template v-if="code">
            <h2 class="title">{{ quote?.name || code }}</h2>
            <span class="muted num">{{ quote?.symbol || code }}</span>
            <Tag v-if="quote?.industry" :value="quote.sub_industry ? `${quote.industry} · ${quote.sub_industry}` : quote.industry" severity="secondary" />
          </template>
          <StockPicker placeholder="搜索股票：代码或名称" @select="pick" @submit="pick" />
        </div>
        <div v-if="code" class="row">
          <WatchStar :code="code" labelled />
          <Button label="分析这只股票" icon="pi pi-play" size="small" @click="analyse" />
        </div>
      </div>
      <!-- The latest quote, or, while the mouse is on the K-line, the bar under it. -->
      <div v-if="code && card" class="stats" :class="{ history: card.history }">
        <span :class="card.history ? 'on-bar' : 'muted'">{{ card.minute ? '分时' : card.history ? 'K线' : '行情日' }} <b class="num">{{ card.date }}</b></span>
        <span>{{ card.minute ? '价格' : card.history ? '收盘' : '最新价' }} <b :class="['num', upDownClass(card.pct)]">{{ card.price?.toFixed(2) ?? '—' }}</b></span>
        <span>涨幅 <b :class="['num', upDownClass(card.pct)]">{{ formatPct(card.pct) }}</b></span>
        <span v-if="card.minute">均价 <b class="num">{{ card.avg?.toFixed(2) ?? '—' }}</b></span>
        <span>开 <b class="num">{{ card.open?.toFixed(2) ?? '—' }}</b></span>
        <span>高 <b class="num">{{ card.high?.toFixed(2) ?? '—' }}</b></span>
        <span>低 <b class="num">{{ card.low?.toFixed(2) ?? '—' }}</b></span>
        <span v-if="quote && !card.minute" :title="card.history
          ? (card.flow === null ? `东方财富个股资金流只保留最近约 120 个交易日（本地自 ${flows?.since || '—'} 起），更早的没有数据` : '东方财富主力净流入（超大单 + 大单）' + (onBar?.period !== 'day' ? '，按日相加' : ''))
          : `资金流：${quote.flow.note}`">{{ card.history ? '主力净流入' : quote.flow.label }}
          <b :class="['num', upDownClass(card.flow)]">{{ formatYuan(card.flow, true) }}</b></span>
        <span v-if="!card.minute">换手率 <b class="num">{{ formatPct(card.turnover, false) }}</b></span>
        <span>{{ card.minute ? '该分钟成交额' : '成交额' }} <b class="num">{{ formatYuan(card.amount) }}</b></span>
        <span>{{ card.minute ? '该分钟成交量' : '成交量' }} <b class="num">{{ formatLots(card.volume) }}</b></span>
        <span :title="card.history ? '按当日收盘价 × 最新总股本估算' : ''">总市值 <b class="num">{{ formatYuan(card.total_mv) }}</b></span>
        <span v-if="card.history" class="muted small">鼠标移开恢复最新行情</span>
      </div>
      <Message v-if="code && error" severity="warn" class="warn">{{ error }}（本地行情快照里没有这只股票，仍可查看 K 线和发起分析）</Message>
    </div>

    <div v-if="code" class="card">
      <KlineChart :ticker="code" full fit external @hover="(h) => (hover = h)" />
    </div>
    <div v-else class="card muted empty">输入股票代码或名称，查看行情和 K 线。从「行情」表中点击一只股票也会打开这里。</div>
  </div>
</template>

<style scoped>
.page > * + * { margin-top: 8px; }
.head { padding: 10px 14px; }
.between { justify-content: space-between; }
.title { margin: 0; font-size: 18px; }
.stats { display: flex; flex-wrap: wrap; gap: 6px 20px; margin-top: 8px; font-size: 13px; color: var(--muted); }
.stats b { color: var(--text); font-weight: 600; margin-left: 4px; }
.stats b.up { color: var(--up); }
.stats b.down { color: var(--down); }
.warn { margin-top: 8px; }
.empty { text-align: center; padding: 48px 16px; }
.stats.history { background: #eff6ff; border-radius: 6px; }
.on-bar { color: #2563eb; }
.small { font-size: 12px; }
</style>
