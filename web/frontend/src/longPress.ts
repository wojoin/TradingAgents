// Long-press on a table row: hold a row for LONG_PRESS_MS without moving to open a menu for it.
// The row is found by the element marked ``data-code`` inside it. The click that ends a long
// press is swallowed, so it does not also open the row.
export const LONG_PRESS_MS = 500

export function useLongPress(open: (event: PointerEvent, code: string) => void) {
  let timer: number | null = null
  let start: { x: number; y: number } | null = null
  let swallow = false

  function cancel() {
    if (timer !== null) window.clearTimeout(timer)
    timer = null
    start = null
  }

  function down(e: PointerEvent) {
    if (e.button !== 0) return
    const code = (e.target as HTMLElement).closest('tr')?.querySelector<HTMLElement>('[data-code]')?.dataset.code
    if (!code) return
    cancel()
    start = { x: e.clientX, y: e.clientY }
    timer = window.setTimeout(() => {
      timer = null
      swallow = true
      window.setTimeout(() => (swallow = false), 600)
      open(e, code)
    }, LONG_PRESS_MS)
  }

  function move(e: PointerEvent) {
    if (start && Math.hypot(e.clientX - start.x, e.clientY - start.y) > 8) cancel()
  }

  return {
    // v-on="handlers" on the element around the table
    handlers: { pointerdown: down, pointermove: move, pointerup: cancel, pointerleave: cancel, pointercancel: cancel },
    swallowed: () => swallow,
    cancel,
  }
}
