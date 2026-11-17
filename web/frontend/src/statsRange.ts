// The span picker of the market stats cards: one per card, remembered in this browser.
import { ref, watch, type Ref } from 'vue'
import type { StatsRange } from './api'

export const RANGES: { value: StatsRange; label: string }[] = [
  { value: '1d', label: '当日' }, { value: '60d', label: '近60天' }, { value: '6m', label: '半年' }, { value: '1y', label: '一年' },
]
export function rangeRef(key: string): Ref<StatsRange> {
  let v: StatsRange = '60d'
  try {
    const s = localStorage.getItem(key)
    if (RANGES.some((r) => r.value === s)) v = s as StatsRange
  } catch {
    /* storage blocked: the default */
  }
  const r = ref<StatsRange>(v)
  watch(r, (x) => {
    try {
      localStorage.setItem(key, x)
    } catch {
      /* storage blocked */
    }
  })
  return r
}
