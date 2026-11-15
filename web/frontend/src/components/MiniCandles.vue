<script setup lang="ts">
import { computed } from 'vue'

// A small candlestick chart drawn from daily changes (%): each day opens at the previous
// close; red up, green down (A-share colours), with a short wick either side.
const props = withDefaults(defineProps<{ changes?: number[]; height?: number }>(), {
  changes: () => [-3, 2, 5, 10, -6],
  height: 22,
})

const W = 30
const H = 24
const PAD = 1.5
const BODY = 3.6
const candles = computed(() => {
  let price = 100
  const bars = props.changes.map((pct) => {
    const open = price
    const close = open * (1 + pct / 100)
    price = close
    return { open, close, high: Math.max(open, close) * 1.008, low: Math.min(open, close) * 0.992 }
  })
  const hi = Math.max(...bars.map((b) => b.high))
  const lo = Math.min(...bars.map((b) => b.low))
  const y = (v: number) => PAD + ((hi - v) / (hi - lo)) * (H - 2 * PAD)
  const step = W / bars.length
  return bars.map((b, i) => {
    const top = y(Math.max(b.open, b.close))
    return {
      x: step * i + step / 2, top, height: Math.max(y(Math.min(b.open, b.close)) - top, 0.6),
      wickTop: y(b.high), wickBottom: y(b.low), color: b.close >= b.open ? '#ef4444' : '#22c55e',
    }
  })
})
</script>

<template>
  <svg :height="height" :width="(height * W) / H" :viewBox="`0 0 ${W} ${H}`" aria-hidden="true">
    <g v-for="(c, i) in candles" :key="i">
      <line :x1="c.x" :x2="c.x" :y1="c.wickTop" :y2="c.wickBottom" :stroke="c.color" stroke-width="0.9" stroke-linecap="round" />
      <rect :x="c.x - BODY / 2" :y="c.top" :width="BODY" :height="c.height" rx="0.5" :fill="c.color" />
    </g>
  </svg>
</template>
