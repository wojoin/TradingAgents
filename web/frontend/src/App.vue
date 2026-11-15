<script setup lang="ts">
import Toast from 'primevue/toast'
</script>

<template>
  <header class="top">
    <div class="top-inner">
      <span class="brand"><i class="pi pi-chart-line" /> TradingAgents</span>
      <nav>
        <RouterLink to="/" exact-active-class="active">发起分析</RouterLink>
        <RouterLink to="/reports" active-class="active">分析报告</RouterLink>
      </nav>
    </div>
  </header>
  <RouterView />
  <Toast position="top-right" />
</template>

<style scoped>
.top { background: #ffffff; border-bottom: 1px solid var(--border); }
.top-inner { max-width: 1280px; margin: 0 auto; padding: 12px 16px; display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
.brand { font-weight: 700; font-size: 16px; display: flex; gap: 8px; align-items: center; }
nav { display: flex; gap: 16px; }
nav a { text-decoration: none; color: var(--muted); padding: 4px 0; border-bottom: 2px solid transparent; }
nav a.active { color: var(--text); border-bottom-color: #2563eb; }
</style>
