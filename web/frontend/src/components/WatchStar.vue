<script setup lang="ts">
import { ref } from 'vue'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import Popover from 'primevue/popover'
import { useToast } from 'primevue/usetoast'
import { useWatchlist } from '../watchlist'
import GroupDialog from './GroupDialog.vue'

// A star for one stock: filled when it sits in any watchlist group; a click lists the
// groups to tick it into or out of, and can start a new group.
const props = defineProps<{ code: string; labelled?: boolean }>()
const toast = useToast()
const watchlist = useWatchlist()
const pop = ref<InstanceType<typeof Popover>>()
const creating = ref(false)
const busy = ref(false)
const error = ref('')

async function toggle(id: string) {
  try {
    await watchlist.toggle(id, props.code)
  } catch (e) {
    toast.add({ severity: 'error', summary: '自选更新失败', detail: e instanceof Error ? e.message : String(e), life: 5000 })
  }
}

async function create(name: string, color: string) {
  busy.value = true
  error.value = ''
  try {
    const g = await watchlist.create(name, color)
    await watchlist.add(g.id, props.code)
    creating.value = false
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <span class="wrap" @click.stop>
    <Button v-if="labelled" :label="watchlist.has(code) ? '已自选' : '加自选'"
            :icon="watchlist.has(code) ? 'pi pi-star-fill' : 'pi pi-star'" severity="secondary" outlined size="small"
            @click="pop?.toggle($event)" />
    <button v-else class="star" :class="{ on: watchlist.has(code) }" :title="watchlist.has(code) ? '自选分组' : '加入自选'"
            @click="pop?.toggle($event)">
      <i :class="watchlist.has(code) ? 'pi pi-star-fill' : 'pi pi-star'" />
    </button>
    <Popover ref="pop">
      <div class="menu">
        <div class="title">加入自选分组</div>
        <div v-if="!watchlist.state.groups.length" class="muted small">还没有分组</div>
        <label v-for="g in watchlist.state.groups" :key="g.id" class="item">
          <Checkbox :model-value="watchlist.inGroup(g.id, code)" binary @update:model-value="toggle(g.id)" />
          <span class="dot" :style="{ background: g.color }" />
          <span>{{ g.name }}</span>
          <span class="muted small">{{ g.codes.length }}</span>
        </label>
        <button v-if="watchlist.state.groups.length < watchlist.state.max" class="link" @click="creating = true">
          <i class="pi pi-plus" /> 新建分组
        </button>
      </div>
    </Popover>
    <GroupDialog v-model:visible="creating" title="新建分组并加入" :busy="busy" :error="error" @save="create" />
  </span>
</template>

<style scoped>
.wrap { display: inline-flex; }
.star { border: 0; background: none; cursor: pointer; color: #c0c6cf; padding: 2px 4px; }
.star.on, .star:hover { color: #f59e0b; }
.menu { display: flex; flex-direction: column; gap: 6px; min-width: 180px; max-height: 320px; overflow-y: auto; }
.title { font-weight: 600; font-size: 13px; margin-bottom: 2px; }
.item { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex: none; }
.link { border: 0; background: none; color: #2563eb; cursor: pointer; padding: 4px 0 0; font: inherit; font-size: 13px; text-align: left; }
.small { font-size: 12px; }
</style>
