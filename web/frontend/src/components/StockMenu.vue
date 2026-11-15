<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import ContextMenu from 'primevue/contextmenu'
import Dialog from 'primevue/dialog'
import Textarea from 'primevue/textarea'
import { useToast } from 'primevue/usetoast'
import { useWatchlist } from '../watchlist'

// The menu for one stock, opened by a long press or a right-click on a table row:
//   分组        every watchlist group, the stock's own in dark; a click adds or removes it
//   移到最前/最后 within ``groupId`` (the 自选 page only)
//   笔记        the stock's note, the same in every group and page
//   查看 / 分析  with ``extras`` (the 行情 page)
const props = defineProps<{ groupId?: string | null; extras?: boolean }>()
const emit = defineEmits<{ moved: [] }>()
const router = useRouter()
const toast = useToast()
const watchlist = useWatchlist()
const menu = ref<InstanceType<typeof ContextMenu>>()
const target = ref<{ code: string; name: string } | null>(null)
const note = ref({ open: false, text: '', busy: false })

const items = computed(() => {
  const t = target.value
  if (!t) return []
  const code = t.code
  const out: Record<string, unknown>[] = [{
    label: '分组', icon: 'pi pi-folder',
    items: watchlist.state.groups.map((g) => ({
      label: g.name, color: g.color, member: g.codes.includes(code),
      command: () => act(() => watchlist.toggle(g.id, code)),
    })),
  }]
  if (props.groupId) {
    out.push(
      { label: '移到最前', icon: 'pi pi-angle-double-up', command: () => act(() => move('top')) },
      { label: '移到最后', icon: 'pi pi-angle-double-down', command: () => act(() => move('bottom')) },
    )
  }
  out.push({ separator: true }, {
    label: watchlist.state.notes[code] ? '笔记（已有）' : '笔记', icon: 'pi pi-pencil', command: openNote,
  })
  if (props.extras) {
    out.push({ separator: true },
      { label: '查看个股', icon: 'pi pi-chart-line', command: () => router.push(`/stock/${code}`) },
      { label: '分析这只股票', icon: 'pi pi-play', command: () => router.push({ path: '/analysis', query: { ticker: code } }) })
  }
  return out
})

async function act(fn: () => Promise<unknown>) {
  try {
    await fn()
  } catch (e) {
    toast.add({ severity: 'error', summary: '操作失败', detail: e instanceof Error ? e.message : String(e), life: 5000 })
  }
}

async function move(to: 'top' | 'bottom') {
  if (!props.groupId || !target.value) return
  await watchlist.move(props.groupId, target.value.code, to)
  emit('moved')
}

function openNote() {
  if (!target.value) return
  note.value = { open: true, text: watchlist.state.notes[target.value.code]?.text || '', busy: false }
}

async function saveNote() {
  if (!target.value) return
  note.value.busy = true
  await act(() => watchlist.setNote(target.value!.code, note.value.text))
  note.value.busy = false
  note.value.open = false
}

const otherGroups = computed(() =>
  target.value ? watchlist.state.groups.filter((g) => g.codes.includes(target.value!.code)).map((g) => g.name) : [],
)

function open(event: Event, code: string, name?: string | null) {
  target.value = { code, name: name || code }
  menu.value?.show(event)
}

defineExpose({ open })
</script>

<template>
  <ContextMenu ref="menu" :model="items">
    <template #item="{ item, props: p, hasSubmenu }">
      <a v-bind="p.action" class="menu-item" :class="{ member: item.member }">
        <span v-if="item.color" class="dot" :style="{ background: item.color }" />
        <i v-else-if="item.icon" :class="item.icon" />
        <span class="menu-label">{{ item.label }}</span>
        <i v-if="item.member" class="pi pi-check check" />
        <i v-if="hasSubmenu" class="pi pi-angle-right sub" />
      </a>
    </template>
  </ContextMenu>
  <Dialog v-model:visible="note.open" modal :header="`笔记 · ${target?.name || ''}`" :style="{ width: '460px' }">
    <Textarea v-model="note.text" rows="7" maxlength="2000" auto-resize class="note-text"
              placeholder="写下这只股票的看法、买卖计划、关注点…" />
    <div class="muted small note-foot">
      <span>{{ note.text.length }} / 2000</span>
      <span>笔记属于这只股票，各个分组和页面看到的都是同一份<template v-if="otherGroups.length">（所在分组：{{ otherGroups.join('、') }}）</template></span>
    </div>
    <div v-if="target && watchlist.state.notes[target.code]" class="muted small">
      上次修改 {{ watchlist.state.notes[target.code].updated.replace('T', ' ') }}
    </div>
    <template #footer>
      <Button label="取消" severity="secondary" text @click="note.open = false" />
      <Button label="保存" :loading="note.busy" @click="saveNote" />
    </template>
  </Dialog>
</template>

<style scoped>
.menu-item { display: flex; align-items: center; gap: 8px; padding: 7px 12px; cursor: pointer; color: var(--text); text-decoration: none; min-width: 150px; }
.menu-item.member { background: #1f2937; color: #fff; font-weight: 600; }
.menu-item .menu-label { flex: 1; }
.menu-item .check { font-size: 12px; }
.menu-item .sub { font-size: 12px; color: var(--muted); }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex: none; }
.note-text { width: 100%; }
.note-foot { display: flex; justify-content: space-between; gap: 12px; margin: 6px 0; }
.small { font-size: 12px; }
</style>
