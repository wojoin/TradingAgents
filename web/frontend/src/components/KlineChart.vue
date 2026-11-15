<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type Time,
} from 'lightweight-charts'
import { api, type Bar } from '../api'

// Daily candles with MA5/10/20 and volume; A-share colours (red up, green down).
const props = defineProps<{ ticker: string; end?: string | null; markDate?: string | null; days?: number }>()
const el = ref<HTMLDivElement>()
const error = ref('')
const loading = ref(false)
const last = ref<Bar | null>(null)
let chart: IChartApi | null = null

const UP = '#e5484d'
const DOWN = '#1f9d55'
const MAS: [number, string][] = [[5, '#f59e0b'], [10, '#3b82f6'], [20, '#a855f7']]

function movingAverage(bars: Bar[], n: number) {
  const out: { time: Time; value: number }[] = []
  let sum = 0
  bars.forEach((b, i) => {
    sum += b.close
    if (i >= n) sum -= bars[i - n].close
    if (i >= n - 1) out.push({ time: b.time as Time, value: +(sum / n).toFixed(3) })
  })
  return out
}

async function draw() {
  if (!el.value) return
  chart?.remove()
  chart = null
  error.value = ''
  loading.value = true
  try {
    const { bars } = await api.kline(props.ticker, props.end || undefined, props.days ?? 250)
    if (!bars.length) throw new Error('没有行情数据')
    last.value = bars[bars.length - 1]
    chart = createChart(el.value, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: '#ffffff' }, textColor: '#4b5563', panes: { separatorColor: '#e3e7ec' } },
      grid: { vertLines: { color: '#f1f3f6' }, horzLines: { color: '#f1f3f6' } },
      rightPriceScale: { borderColor: '#e3e7ec' },
      timeScale: { borderColor: '#e3e7ec' },
      localization: { locale: 'zh-CN' },
    })
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN, wickUpColor: UP, wickDownColor: DOWN,
    })
    candles.setData(bars.map((b) => ({ time: b.time as Time, open: b.open, high: b.high, low: b.low, close: b.close })))
    for (const [n, color] of MAS) {
      const line = chart.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: `MA${n}` })
      line.setData(movingAverage(bars, n))
    }
    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceLineVisible: false }, 1)
    volume.setData(bars.map((b) => ({ time: b.time as Time, value: b.volume, color: b.close >= b.open ? UP : DOWN })))
    chart.panes()[1]?.setHeight(110)
    if (props.markDate) {
      const at = [...bars].reverse().find((b) => b.time <= props.markDate!)
      if (at) {
        createSeriesMarkers(candles, [
          { time: at.time as Time, position: 'aboveBar', color: '#2563eb', shape: 'arrowDown', text: '分析日' },
        ])
      }
    }
    chart.timeScale().fitContent()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(draw)
watch(() => [props.ticker, props.end, props.days], draw)
onBeforeUnmount(() => chart?.remove())
</script>

<template>
  <div>
    <div class="row legend">
      <strong>{{ ticker }} 日K线</strong>
      <span v-if="last" class="muted">
        {{ last.time }} 收 {{ last.close.toFixed(2) }} · 高 {{ last.high.toFixed(2) }} · 低 {{ last.low.toFixed(2) }}
      </span>
      <span class="ma" style="color: #f59e0b">MA5</span>
      <span class="ma" style="color: #3b82f6">MA10</span>
      <span class="ma" style="color: #a855f7">MA20</span>
      <span v-if="loading" class="muted"><i class="pi pi-spin pi-spinner" /> 加载中</span>
    </div>
    <div v-if="error" class="muted error">K线加载失败：{{ error }}</div>
    <div ref="el" class="chart" />
  </div>
</template>

<style scoped>
.legend { margin-bottom: 8px; }
.ma { font-size: 12px; }
.chart { width: 100%; height: 440px; }
.error { padding: 8px 0; }
</style>
