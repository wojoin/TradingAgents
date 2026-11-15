<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import Message from 'primevue/message'
import Tag from 'primevue/tag'
import { useToast } from 'primevue/usetoast'
import { api, formatLots, formatPct, formatYuan, upDownClass, type Quote } from '../api'
import KlineChart from '../components/KlineChart.vue'
import StockPicker from '../components/StockPicker.vue'
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

watch(() => props.code, load, { immediate: true })
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
      <div v-if="code && quote" class="stats">
        <span>最新价 <b :class="['num', upDownClass(quote.pct_chg)]">{{ quote.price?.toFixed(2) }}</b></span>
        <span>涨幅 <b :class="['num', upDownClass(quote.pct_chg)]">{{ formatPct(quote.pct_chg) }}</b></span>
        <span :title="`资金流：${quote.flow.note}`">{{ quote.flow.label }} <b :class="['num', upDownClass(quote.main_flow)]">{{ formatYuan(quote.main_flow, true) }}</b></span>
        <span>换手率 <b class="num">{{ formatPct(quote.turnover, false) }}</b></span>
        <span>成交额 <b class="num">{{ formatYuan(quote.amount) }}</b></span>
        <span>成交量 <b class="num">{{ formatLots(quote.volume) }}</b></span>
        <span>总市值 <b class="num">{{ formatYuan(quote.total_mv) }}</b></span>
        <span class="muted">行情日 {{ quote.date }}</span>
      </div>
      <Message v-if="code && error" severity="warn" class="warn">{{ error }}（本地行情快照里没有这只股票，仍可查看 K 线和发起分析）</Message>
    </div>

    <div v-if="code" class="card">
      <KlineChart :ticker="code" full fit />
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
</style>
