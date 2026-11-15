<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'

// Reports are model output: render Markdown, never raw HTML inside it.
const md = new MarkdownIt({ html: false, linkify: true, breaks: false })
const props = defineProps<{ source: string }>()
const html = computed(() => md.render(props.source || ''))
</script>

<template>
  <div class="markdown" v-html="html" />
</template>
