<script setup lang="ts">
// Delete a saved report, after a confirmation. The server moves it to reports/.trash/, so a
// mistake can be undone by moving the folder back.
import { ref } from 'vue'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import { api } from '../api'

const props = defineProps<{ reportId: string; label?: string; ticker?: string | null; date?: string | null }>()
const emit = defineEmits<{ deleted: [id: string] }>()
const open = ref(false)
const busy = ref(false)
const error = ref('')

async function remove() {
  busy.value = true
  error.value = ''
  try {
    await api.deleteReport(props.reportId)
    open.value = false
    emit('deleted', props.reportId)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Button :label="label" icon="pi pi-trash" severity="danger" text size="small" :aria-label="label || '删除报告'"
          title="删除报告" @click.stop="open = true" />
  <Dialog v-model:visible="open" modal header="删除报告" :style="{ width: '380px' }">
    <p class="msg">确定删除 <b>{{ ticker || reportId }}</b>{{ date ? `（分析日 ${date}）` : '' }} 的分析报告？</p>
    <p class="muted small">报告会移到 <code>reports/.trash/</code>，误删时可把文件夹移回恢复。</p>
    <p v-if="error" class="bad small">删除失败：{{ error }}</p>
    <template #footer>
      <Button label="取消" severity="secondary" text :disabled="busy" @click="open = false" />
      <Button label="删除" severity="danger" icon="pi pi-trash" :loading="busy" @click="remove" />
    </template>
  </Dialog>
</template>

<style scoped>
.msg { margin: 0 0 8px; }
.small { font-size: 12px; }
.bad { color: var(--up); }
code { font-size: 12px; }
</style>
