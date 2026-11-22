<script setup lang="ts">
// Lines (or bars) over trading days (lightweight-charts), with a legend that shows the values on the
// day under the mouse, or on the last day. With ``pick``, the line nearest the mouse is drawn
// thicker and named beside it.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ColorType, createChart, HistogramSeries, LineSeries, type IChartApi, type ISeriesApi, type SeriesType, type Time } from 'lightweight-charts'

export interface Line {
  name: string
  color: string
  points: { time: string; value: number; color?: string }[]
  bars?: boolean          // a bar per day (each may have its own colour) instead of a line
}

// Slot ``tooltip``: a box over the first line's point on the day under the mouse, given that day.
// Slot ``legend`` (one-row legend only): more on the shown day, after the lines' values.
// ``rows``: line names grouped into legend rows (any line not named goes on a row of its own at
// the end); without it the legend is one wrapping row.
// ``levels``: labelled horizontal lines (on the first line's scale), shown whether or not the
// data reaches them; ``range``: the value axis fixed to [min, max] instead of fitted to the data;
// ``markers``: a dot on every point; ``sync``: a day hovered on another chart, to put this chart's
// crosshair and legend on too (charts side by side then follow each other, given each other's ``hover``);
// ``tight``: less room above and below the data (5% / 5% instead of 20% / 10%).
const props = withDefaults(defineProps<{
  lines: Line[]; format?: (v: number) => string; height?: number; pick?: boolean; rows?: string[][]
  levels?: { value: number; title: string; color?: string }[]; range?: [number, number]; markers?: boolean
  sync?: string | null; tight?: boolean
}>(), {
  format: (v: number) => v.toLocaleString('zh-CN'),
  height: 240,
  pick: false,
})

// ``hover``: the day under the mouse, or null when it leaves the chart.
const emit = defineEmits<{ hover: [day: string | null] }>()

const el = ref<HTMLDivElement>()
const hover = ref<string | null>(null)
// The line under the mouse (within PICK_PX of it): its index in ``lines``, value and where to label it.
const PICK_PX = 14
// Where the tooltip box points: the first line's point on the hovered day, in the chart's pixels.
const tipAt = ref<{ x: number; y: number } | null>(null)
const near = ref<{ i: number; value: number; x: number; y: number } | null>(null)
let chart: IChartApi | null = null
let series: ISeriesApi<SeriesType>[] = []

const days = computed(() => props.lines[0]?.points.map((p) => p.time) || [])
const shownDay = computed(() => hover.value ?? (props.sync && days.value.includes(props.sync) ? props.sync : null)
  ?? days.value[days.value.length - 1] ?? null)
// A bar's own colour (e.g. red up / green down) goes on its legend dot and value too.
const legend = computed(() =>
  props.lines.map((l) => {
    const p = l.points.find((x) => x.time === shownDay.value)
    return { name: l.name, color: p?.color ?? l.color, valueColor: p?.color, value: p?.value ?? null }
  }),
)
const legendRows = computed(() => {
  const items = legend.value
  if (!props.rows) return null
  const byName = new Map(items.map((x) => [x.name, x]))
  const named = new Set(props.rows.flat())
  return [...props.rows.map((r) => r.flatMap((n) => byName.get(n) ?? [])), items.filter((x) => !named.has(x.name))]
    .filter((r) => r.length)
})

// Above the point, centred on it; below it near the top, kept inside at the sides.
const tipStyle = computed(() => {
  const t = tipAt.value
  if (!t) return {}
  const w = el.value?.clientWidth ?? 0
  const tx = t.x < 70 ? '0%' : t.x > w - 130 ? '-100%' : '-50%'
  const below = t.y < 80
  return { left: `${t.x}px`, top: `${below ? t.y + 12 : t.y - 12}px`, transform: `translate(${tx}, ${below ? '0' : '-100%'})` }
})

// Right of the mouse, or left of it in the chart's right third, so the label stays inside.
const pickStyle = computed(() => {
  const n = near.value
  if (!n) return {}
  const flip = n.x > (el.value?.clientWidth ?? 0) * 0.66
  return { left: `${n.x + (flip ? -12 : 12)}px`, top: `${Math.max(n.y - 30, 0)}px`, transform: flip ? 'translateX(-100%)' : 'none' }
})

function formatDay(t: Time): string {
  if (typeof t === 'string') return t
  if (typeof t === 'number') return new Date(t * 1000).toISOString().slice(0, 10)
  return `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}`
}

function draw() {
  if (!chart) return
  for (const s of series) chart.removeSeries(s)
  const single = days.value.length <= 1          // one day: a dot, since a line needs two
  const priceFormat = { type: 'custom' as const, formatter: props.format, minMove: 0.01 }
  series = props.lines.map((l) => {
    if (l.bars) {
      const s = chart!.addSeries(HistogramSeries, { color: l.color, priceLineVisible: false, lastValueVisible: false, priceFormat })
      s.setData(l.points.map((p) => ({ time: p.time as Time, value: p.value, color: p.color })))
      return s
    }
    const s = chart!.addSeries(LineSeries, {
      color: l.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
      pointMarkersVisible: single || props.markers, pointMarkersRadius: props.markers ? 3 : 4, priceFormat,
      ...(props.range ? { autoscaleInfoProvider: () => ({ priceRange: { minValue: props.range![0], maxValue: props.range![1] } }) } : {}),
    })
    s.setData(l.points.map((p) => ({ time: p.time as Time, value: p.value })))
    return s
  })
  // The labelled levels, drawn on the first series (they share its scale).
  if (series.length && props.levels) {
    for (const lv of props.levels) {
      series[0].createPriceLine({ price: lv.value, color: lv.color ?? '#c0c6cf', lineWidth: 1, lineStyle: 2,
                                  axisLabelVisible: true, title: lv.title })
    }
  }
  chart.timeScale().fitContent()
  near.value = null
}

onMounted(() => {
  if (!el.value) return
  chart = createChart(el.value, {
    autoSize: true,
    layout: { background: { type: ColorType.Solid, color: '#ffffff' }, textColor: '#4b5563', attributionLogo: false },
    grid: { vertLines: { color: '#f1f3f6' }, horzLines: { color: '#f1f3f6' } },
    rightPriceScale: { borderColor: '#e3e7ec', ...(props.tight ? { scaleMargins: { top: 0.05, bottom: 0.05 } } : {}) },
    timeScale: { borderColor: '#e3e7ec' },
    localization: { locale: 'zh-CN', timeFormatter: formatDay },
    handleScroll: false,
    handleScale: false,
  })
  chart.subscribeCrosshairMove((p) => {
    // Our own setCrosshairPosition for ``sync`` (a day but no mouse event) is not a hover; the mouse
    // leaving comes without an event too, and is one (when the mouse was on us: a following chart
    // clearing its crosshair is not).
    if (!p.sourceEvent && (p.time !== undefined || hover.value === null)) return
    hover.value = p.time === undefined ? null : formatDay(p.time)
    emit('hover', hover.value)
    const v0 = series[0] && p.point ? (p.seriesData.get(series[0]) as { value?: number } | undefined)?.value : undefined
    const y0 = v0 === undefined ? null : series[0].priceToCoordinate(v0)
    tipAt.value = p.point && y0 !== null ? { x: p.point.x, y: y0 } : null
    if (!props.pick) return
    let best: { i: number; value: number; d: number } | null = null
    if (p.point && p.time !== undefined) {
      series.forEach((s, i) => {
        const v = (p.seriesData.get(s) as { value?: number } | undefined)?.value
        const y = v === undefined ? null : s.priceToCoordinate(v)
        if (v === undefined || y === null) return
        const d = Math.abs(y - p.point!.y)
        if (d <= PICK_PX && (!best || d < best.d)) best = { i, value: v, d }
      })
    }
    const b = best as { i: number; value: number; d: number } | null
    if ((near.value?.i ?? -1) !== (b?.i ?? -1)) {
      series.forEach((s, i) => s.applyOptions({ lineWidth: b && i === b.i ? 4 : 2 }))
    }
    near.value = b && p.point ? { i: b.i, value: b.value, x: p.point.x, y: p.point.y } : null
  })
  draw()
})

watch(() => props.lines, draw, { deep: false })

// Follow another chart's hovered day: the crosshair on our first series' point that day.
watch(() => props.sync, (day) => {
  if (!chart || !series.length || hover.value) return
  const p = day ? props.lines[0]?.points.find((x) => x.time === day) : undefined
  if (p) chart.setCrosshairPosition(p.value, p.time as Time, series[0])
  else chart.clearCrosshairPosition()
  // The tooltip box too, over that point.
  const x = p ? chart.timeScale().timeToCoordinate(p.time as Time) : null
  const y = p ? series[0].priceToCoordinate(p.value) : null
  tipAt.value = x !== null && y !== null ? { x, y } : null
})
// The day the tooltip box is for: the mouse's, or the followed one.
const tipDay = computed(() => hover.value ?? (props.sync && tipAt.value ? props.sync : null))
onBeforeUnmount(() => {
  chart?.remove()
  chart = null
})
</script>

<template>
  <div>
    <div v-if="legendRows" class="legend rows">
      <div class="muted">{{ shownDay || '—' }}</div>
      <div v-for="(row, i) in legendRows" :key="i" class="lrow">
        <span v-for="l in row" :key="l.name"><i class="dot" :style="{ background: l.color }" />{{ l.name }}
          <b :style="l.valueColor ? { color: l.valueColor } : undefined">{{ l.value === null ? '—' : format(l.value) }}</b></span>
      </div>
    </div>
    <div v-else class="legend">
      <span class="muted">{{ shownDay || '—' }}</span>
      <span v-for="l in legend" :key="l.name"><i class="dot" :style="{ background: l.color }" />{{ l.name }}
        <b :style="l.valueColor ? { color: l.valueColor } : undefined">{{ l.value === null ? '—' : format(l.value) }}</b></span>
      <slot name="legend" :day="shownDay" />
    </div>
    <div class="plot">
      <div ref="el" :style="{ height: `${height}px` }" />
      <div v-if="$slots.tooltip && tipAt && tipDay" class="tip" :style="tipStyle">
        <slot name="tooltip" :day="tipDay" />
      </div>
      <div v-if="near && lines[near.i]" class="pick" :style="pickStyle">
        <i class="dot" :style="{ background: lines[near.i].color }" />{{ lines[near.i].name }}
        <b>{{ format(near.value) }}</b>
      </div>
    </div>
  </div>
</template>

<style scoped>
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; margin-bottom: 4px; font-variant-numeric: tabular-nums; }
.legend.rows { flex-direction: column; gap: 2px; }
.lrow { display: flex; flex-wrap: wrap; gap: 2px 14px; padding-left: 6px; }
.plot { position: relative; }
.pick { position: absolute; z-index: 3; pointer-events: none; white-space: nowrap; font-size: 12px; padding: 3px 8px;
        background: #fff; border: 1px solid #e3e7ec; border-radius: 6px; box-shadow: 0 2px 6px rgba(0, 0, 0, .08);
        font-variant-numeric: tabular-nums; }
.tip { position: absolute; z-index: 3; pointer-events: none; white-space: nowrap; font-size: 12px; line-height: 1.7;
       padding: 6px 10px; background: #fff; border: 1px solid #e3e7ec; border-radius: 6px;
       box-shadow: 0 2px 8px rgba(0, 0, 0, .12); font-variant-numeric: tabular-nums; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
</style>
