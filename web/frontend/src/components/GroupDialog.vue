<script setup lang="ts">
import { ref, watch } from 'vue'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import { GROUP_COLORS } from '../watchlist'

// Create or edit a watchlist group: a name (1-20 characters) and a colour.
const props = defineProps<{ visible: boolean; title: string; name?: string; color?: string; busy?: boolean; error?: string }>()
const emit = defineEmits<{ 'update:visible': [v: boolean]; save: [name: string, color: string] }>()
const name = ref('')
const color = ref(GROUP_COLORS[5])

watch(() => props.visible, (open) => {
  if (open) {
    name.value = props.name || ''
    color.value = props.color || GROUP_COLORS[5]
  }
})
</script>

<template>
  <Dialog :visible="visible" modal :header="title" :style="{ width: '380px' }" @update:visible="emit('update:visible', $event)">
    <div class="form">
      <label>名称</label>
      <InputText v-model="name" maxlength="20" placeholder="如：科技、白酒、观察中" autofocus @keyup.enter="name.trim() && emit('save', name.trim(), color)" />
      <label>颜色</label>
      <div class="swatches">
        <button v-for="c in GROUP_COLORS" :key="c" class="swatch" :class="{ on: color === c }" :style="{ background: c }"
                :aria-label="c" @click="color = c" />
        <label class="custom" title="自定义颜色">
          <input v-model="color" type="color" />
          <span>自定义</span>
        </label>
      </div>
      <div class="preview"><span class="dot" :style="{ background: color }" /> {{ name || '分组名称' }}</div>
      <div v-if="error" class="bad">{{ error }}</div>
    </div>
    <template #footer>
      <Button label="取消" severity="secondary" text @click="emit('update:visible', false)" />
      <Button label="保存" :loading="busy" :disabled="!name.trim()" @click="emit('save', name.trim(), color)" />
    </template>
  </Dialog>
</template>

<style scoped>
.form { display: flex; flex-direction: column; gap: 8px; }
.form > label { font-weight: 600; font-size: 13px; }
.swatches { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.swatch { width: 24px; height: 24px; border-radius: 50%; border: 2px solid transparent; cursor: pointer; padding: 0; }
.swatch.on { border-color: #fff; box-shadow: 0 0 0 2px #111827; }
.custom { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--muted); cursor: pointer; }
.custom input { width: 28px; height: 24px; border: 0; padding: 0; background: none; cursor: pointer; }
.preview { display: flex; align-items: center; gap: 6px; margin-top: 4px; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.bad { color: var(--up); font-size: 13px; }
</style>
