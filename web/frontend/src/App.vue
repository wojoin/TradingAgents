<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import Toast from 'primevue/toast'
import BrandMark from './components/BrandMark.vue'
import MiniCandles from './components/MiniCandles.vue'

const route = useRoute()
const MENU = [
  { to: '/watchlist', label: '自选', icon: 'pi pi-star', match: ['/watchlist'] },
  { to: '/stock', label: '个股', icon: 'pi pi-search', match: ['/stock'] },
  { to: '/market', label: '行情', icon: 'pi pi-table', match: ['/market'] },
  { to: '/analysis', label: '分析', icon: 'pi pi-chart-bar', match: ['/analysis', '/reports'] },
]
// A report page belongs to 分析.
const active = computed(() => MENU.find((m) => m.match.some((p) => route.path.startsWith(p)))?.to)

// The menu folds to its icons; the choice is remembered in this browser.
const KEY = 'menu.collapsed'
function stored(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}
const collapsed = ref(stored())
watch(collapsed, (v) => {
  try {
    localStorage.setItem(KEY, v ? '1' : '0')
  } catch {
    /* storage unavailable: the choice lasts for this page only */
  }
})
</script>

<template>
  <div class="shell">
    <aside class="side" :class="{ collapsed }">
      <div class="brand" :title="collapsed ? 'TradingAgents' : undefined">
        <BrandMark /> <MiniCandles class="candles" /> <span class="text">TradingAgents</span>
      </div>
      <nav>
        <RouterLink v-for="m in MENU" :key="m.to" :to="m.to" class="item" :class="{ active: active === m.to }"
                    :title="collapsed ? m.label : undefined">
          <i :class="m.icon" /> <span class="text">{{ m.label }}</span>
        </RouterLink>
      </nav>
      <button class="fold" :title="collapsed ? '展开' : '收起'" :aria-label="collapsed ? '展开菜单' : '收起菜单'"
              @click="collapsed = !collapsed">
        <i :class="collapsed ? 'pi pi-angle-double-right' : 'pi pi-angle-double-left'" />
        <span class="text">收起</span>
      </button>
    </aside>
    <main class="content">
      <RouterView />
    </main>
  </div>
  <Toast position="top-right" />
</template>

<style scoped>
.shell { display: flex; min-height: 100vh; }
.side {
  width: 200px; flex: none; background: #111827; color: #d1d5db;
  position: sticky; top: 0; height: 100vh; padding: 14px 8px;
  display: flex; flex-direction: column; transition: width 0.15s ease;
}
.brand { display: flex; align-items: center; gap: 6px; color: #fff; font-weight: 700; font-size: 15px; padding: 4px 10px 18px; white-space: nowrap; }
nav { display: flex; flex-direction: column; gap: 4px; flex: 1; }
.item, .fold {
  display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 8px;
  color: inherit; text-decoration: none; white-space: nowrap; overflow: hidden;
}
.item:hover, .fold:hover { background: #1f2937; color: #fff; }
.item.active { background: #2563eb; color: #fff; }
.fold { border: 0; background: none; font: inherit; cursor: pointer; color: #9ca3af; }
.side.collapsed { width: 56px; }
.side.collapsed .text, .side.collapsed .candles { display: none; }
.side.collapsed .brand, .side.collapsed .item, .side.collapsed .fold { justify-content: center; padding-left: 0; padding-right: 0; }
.content { flex: 1; min-width: 0; }
@media (max-width: 760px) {
  .shell { flex-direction: column; }
  .side, .side.collapsed { width: auto; height: auto; position: static; flex-direction: row; align-items: center; gap: 12px; padding: 8px 12px; }
  .brand { padding: 0; }
  .brand .text, .fold { display: none; }
  nav { flex-direction: row; flex: none; }
  .item { padding: 8px 10px; }
  .side.collapsed .text { display: inline; }
}
</style>
