<script setup lang="ts">
import Button from 'primevue/button'
import { api } from '../api'

defineProps<{ reportId: string; hasHtml?: boolean; size?: 'small' | 'large' }>()
</script>

<template>
  <div class="row">
    <a :href="api.download(reportId, 'md')" download>
      <Button label="Markdown" icon="pi pi-file" severity="secondary" outlined :size="size" />
    </a>
    <a v-if="hasHtml !== false" :href="api.download(reportId, 'html')" download>
      <Button label="HTML" icon="pi pi-globe" severity="secondary" outlined :size="size" />
    </a>
    <a :href="api.download(reportId, 'zip')" download>
      <Button label="全部 (ZIP)" icon="pi pi-download" :size="size" />
    </a>
  </div>
</template>

<style scoped>
a { text-decoration: none; }
</style>
