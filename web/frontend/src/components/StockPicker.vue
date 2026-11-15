<script setup lang="ts">
import { ref, watch } from 'vue'
import AutoComplete from 'primevue/autocomplete'
import { api, type StockHit } from '../api'

// A stock code or name box that suggests matches as you type.
//   v-model   what the box holds: the chosen stock's code, or the text typed
//   @select   a suggestion was picked (its code)
//   @submit   Enter was pressed (the text, or the picked code)
const props = defineProps<{ modelValue?: string; placeholder?: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; select: [code: string]; submit: [value: string] }>()
const text = ref<string | StockHit>(props.modelValue || '')
const suggestions = ref<StockHit[]>([])

watch(() => props.modelValue, (v) => {
  const current = typeof text.value === 'string' ? text.value : text.value.code
  if ((v || '') !== current) text.value = v || ''
})
watch(text, (v) => emit('update:modelValue', typeof v === 'string' ? v.trim() : v.code))

async function complete(e: { query: string }) {
  suggestions.value = e.query.trim() ? await api.search(e.query.trim()).catch(() => []) : []
}

function selected(e: { value: StockHit }) {
  text.value = e.value
  emit('select', e.value.code)
}

function submit() {
  const v = typeof text.value === 'string' ? text.value.trim() : text.value.code
  if (v) emit('submit', v)
}

defineExpose({ clear: () => (text.value = '') })
</script>

<template>
  <AutoComplete
    v-model="text"
    :suggestions="suggestions"
    :option-label="(s: StockHit) => `${s.code} ${s.name}`"
    :placeholder="props.placeholder || '股票代码或名称，如 300308 / 中际旭创'"
    :disabled="disabled"
    :delay="200"
    class="picker"
    input-class="picker-input"
    @complete="complete"
    @option-select="selected"
    @keyup.enter="submit"
  >
    <template #option="{ option }">
      <span class="num">{{ option.code }}</span>&nbsp;<strong>{{ option.name }}</strong>
      <span class="muted">&nbsp;{{ option.symbol }}</span>
    </template>
  </AutoComplete>
</template>

<style scoped>
.picker { width: 300px; max-width: 100%; }
:deep(.picker-input) { width: 100%; }
</style>
