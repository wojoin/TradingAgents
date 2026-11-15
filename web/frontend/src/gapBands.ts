// Price gaps between adjacent daily candles, drawn as grey bands across the whole price pane.
//   up gap:   today's low  > yesterday's high  -> band from yesterday's high to today's low
//   down gap: today's high < yesterday's low   -> band from today's high  to yesterday's low
// The band's height is the gap's price range, so it follows the price scale as it zooms.
import type { CanvasRenderingTarget2D } from 'fancy-canvas'
import type {
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  PrimitivePaneViewZOrder,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from 'lightweight-charts'

export interface Gap {
  time: string      // the day the gap opened
  prevTime: string  // the trading day before it
  from: number      // the lower price of the band
  to: number        // the upper price of the band
  up: boolean
  high: number      // the day's high and low
  low: number
  prevHigh: number  // the day before's high and low
  prevLow: number
}

// Gaps opened on or after ``since`` (YYYY-MM-DD); all of them without it.
export function findGaps(bars: { time: string; high: number; low: number }[], since?: string): Gap[] {
  const out: Gap[] = []
  for (let i = 1; i < bars.length; i++) {
    if (since && bars[i].time < since) continue
    const prev = bars[i - 1]
    const cur = bars[i]
    const days = { time: cur.time, prevTime: prev.time, high: cur.high, low: cur.low, prevHigh: prev.high, prevLow: prev.low }
    if (cur.low > prev.high) out.push({ ...days, from: prev.high, to: cur.low, up: true })
    else if (cur.high < prev.low) out.push({ ...days, from: cur.high, to: prev.low, up: false })
  }
  return out
}

const FILL = 'rgba(120, 120, 120, 0.14)'

class GapRenderer implements IPrimitivePaneRenderer {
  private readonly bands: { y1: number; y2: number }[]

  constructor(bands: { y1: number; y2: number }[]) {
    this.bands = bands
  }

  draw(target: CanvasRenderingTarget2D) {
    target.useBitmapCoordinateSpace(({ context, bitmapSize, verticalPixelRatio }) => {
      context.fillStyle = FILL
      for (const { y1, y2 } of this.bands) {
        const top = Math.round(Math.min(y1, y2) * verticalPixelRatio)
        const height = Math.max(1, Math.round(Math.abs(y2 - y1) * verticalPixelRatio))
        context.fillRect(0, top, bitmapSize.width, height)
      }
    })
  }
}

class GapView implements IPrimitivePaneView {
  bands: { y1: number; y2: number }[] = []
  private readonly source: GapBands

  constructor(source: GapBands) {
    this.source = source
  }

  update() {
    const series = this.source.series
    if (!series || !this.source.visible) {
      this.bands = []
      return
    }
    this.bands = this.source.gaps.flatMap((g) => {
      const y1 = series.priceToCoordinate(g.from)
      const y2 = series.priceToCoordinate(g.to)
      return y1 === null || y2 === null ? [] : [{ y1, y2 }]
    })
  }

  renderer() {
    return new GapRenderer(this.bands)
  }

  zOrder(): PrimitivePaneViewZOrder {
    return 'bottom'    // under the candles
  }
}

export class GapBands implements ISeriesPrimitive<Time> {
  series: ISeriesApi<SeriesType, Time> | null = null
  gaps: Gap[] = []
  visible = true
  private readonly view = new GapView(this)
  private requestUpdate: (() => void) | null = null

  attached({ series, requestUpdate }: SeriesAttachedParameter<Time>) {
    this.series = series
    this.requestUpdate = requestUpdate
  }

  detached() {
    this.series = null
    this.requestUpdate = null
  }

  updateAllViews() {
    this.view.update()
  }

  paneViews() {
    return [this.view]
  }

  setGaps(gaps: Gap[]) {
    this.gaps = gaps
    this.requestUpdate?.()
  }

  setVisible(visible: boolean) {
    this.visible = visible
    this.requestUpdate?.()
  }
}

// The day six months before ``day`` (YYYY-MM-DD): older gaps say little about today's price.
export function sixMonthsBefore(day: string): string {
  const [y, m, d] = day.split('-').map(Number)
  const month = m - 6 <= 0 ? m + 6 : m - 6
  const year = m - 6 <= 0 ? y - 1 : y
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate()     // a 31st lands on the month's last day
  return `${year}-${String(month).padStart(2, '0')}-${String(Math.min(d, last)).padStart(2, '0')}`
}
