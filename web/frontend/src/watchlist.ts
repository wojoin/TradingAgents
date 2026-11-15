import { reactive } from 'vue'
import { api, type StockNote, type WatchGroup } from './api'

// The watchlist's groups, shared by every page that shows or edits them (自选, 行情, 个股).
const state = reactive({ groups: [] as WatchGroup[], notes: {} as Record<string, StockNote>, max: 256, loaded: false })

export const DEFAULT_GROUP = 'default'   // always there; cannot be deleted

export const GROUP_COLORS = ['#e5484d', '#f59e0b', '#eab308', '#16a34a', '#0ea5e9', '#2563eb', '#7c3aed', '#db2777', '#6b7280', '#111827']

function replace(group: WatchGroup) {
  const i = state.groups.findIndex((g) => g.id === group.id)
  if (i >= 0) state.groups[i] = group
  else state.groups.push(group)
}

export function useWatchlist() {
  async function load() {
    const w = await api.watchlist(false)
    state.groups = w.groups
    state.notes = w.notes || {}
    state.max = w.max_groups
    state.loaded = true
  }
  const has = (code: string) => state.groups.some((g) => g.codes.includes(code))
  const inGroup = (id: string, code: string) => !!state.groups.find((g) => g.id === id)?.codes.includes(code)
  async function create(name: string, color: string) {
    const g = await api.createGroup(name, color)
    replace(g)
    return g
  }
  async function update(id: string, patch: { name?: string; color?: string }) {
    replace(await api.updateGroup(id, patch))
  }
  async function remove(id: string) {
    state.groups = (await api.deleteGroup(id)).groups
  }
  async function add(id: string, code: string) {
    replace(await api.addToGroup(id, code))
  }
  async function drop(id: string, code: string) {
    replace(await api.removeFromGroup(id, code))
  }
  async function toggle(id: string, code: string) {
    return inGroup(id, code) ? drop(id, code) : add(id, code)
  }
  async function move(id: string, code: string, to: 'top' | 'bottom') {
    replace(await api.moveInGroup(id, code, to))
  }
  // A note belongs to the stock: the same in every group.
  async function setNote(code: string, text: string) {
    const { note } = await api.setNote(code, text)
    const notes = { ...state.notes }
    if (note) notes[code] = note
    else delete notes[code]
    state.notes = notes
  }
  if (!state.loaded) load().catch(() => {})
  return { state, has, inGroup, load, create, update, remove, add, drop, toggle, move, setNote }
}
