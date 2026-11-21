<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import Tabs from 'primevue/tabs'
import TabList from 'primevue/tablist'
import Tab from 'primevue/tab'
import TabPanels from 'primevue/tabpanels'
import TabPanel from 'primevue/tabpanel'
import { api, AGENT_LABELS, ratingSeverity, type Report } from '../api'
import KlineChart from '../components/KlineChart.vue'
import MarkdownView from '../components/MarkdownView.vue'
import DownloadButtons from '../components/DownloadButtons.vue'
import DeleteReport from '../components/DeleteReport.vue'
import { useRouter } from 'vue-router'

const props = defineProps<{ id: string }>()
const router = useRouter()
const report = ref<Report | null>(null)
const error = ref('')
const tab = ref('')

const HEADINGS: Record<string, string> = {
  '1_analysts': '分析师团队',
  '2_research': '研究团队',
  '3_trading': '交易团队',
  '4_risk': '风控团队',
  '5_portfolio': '组合经理决策',
}
const decisionFirst = computed(() => {
  const s = report.value?.sections || []
  return [...s.filter((x) => x.folder === '5_portfolio'), ...s.filter((x) => x.folder !== '5_portfolio')]
})

async function load() {
  error.value = ''
  report.value = null
  try {
    report.value = await api.report(props.id)
    tab.value = decisionFirst.value[0]?.folder || ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}
watch(() => props.id, load, { immediate: true })
</script>

<template>
  <div class="page">
    <RouterLink to="/analysis" class="back"><i class="pi pi-arrow-left" /> 返回分析</RouterLink>
    <Message v-if="error" severity="error">报告加载失败：{{ error }}</Message>
    <template v-if="report">
      <div class="card head">
        <div class="row between">
          <div class="row">
            <h2 class="title">{{ report.ticker }}</h2>
            <Tag v-if="report.rating" :value="`评级 ${report.rating}`" :severity="ratingSeverity(report.rating)" />
            <span class="muted">分析日 {{ report.analysis_date }} · 生成于 {{ report.generated }}</span>
          </div>
          <div class="row">
            <a v-if="report.has_html" :href="api.download(report.id, 'html', true)" target="_blank" rel="noopener">
              <Button label="打开 HTML 报告" icon="pi pi-external-link" text />
            </a>
            <DownloadButtons :report-id="report.id" :has-html="report.has_html" />
            <DeleteReport :report-id="report.id" :ticker="report.ticker" :date="report.analysis_date" label="删除"
                          @deleted="router.push('/analysis')" />
          </div>
        </div>
        <div v-if="report.models" class="muted small">{{ report.models }}</div>
      </div>

      <div v-if="report.ticker" class="card">
        <KlineChart :ticker="report.ticker" :end="report.analysis_date" :mark-date="report.analysis_date" />
      </div>

      <div class="card">
        <Tabs v-model:value="tab" scrollable>
          <TabList>
            <Tab v-for="s in decisionFirst" :key="s.folder" :value="s.folder">{{ HEADINGS[s.folder] || s.heading }}</Tab>
          </TabList>
          <TabPanels>
            <TabPanel v-for="s in decisionFirst" :key="s.folder" :value="s.folder">
              <div v-for="a in s.agents" :key="a.file" class="agent">
                <h3 class="agent-name">{{ AGENT_LABELS[a.agent] || a.agent }}</h3>
                <MarkdownView :source="a.content" />
              </div>
            </TabPanel>
          </TabPanels>
        </Tabs>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page > * + * { margin-top: 16px; }
.back { display: inline-flex; gap: 6px; align-items: center; color: var(--muted); text-decoration: none; }
.between { justify-content: space-between; }
.title { margin: 0; font-size: 20px; }
.small { font-size: 12px; margin-top: 6px; }
.agent + .agent { border-top: 1px solid var(--border); margin-top: 16px; padding-top: 8px; }
.agent-name { margin: 8px 0; font-size: 16px; color: #2563eb; }
a { text-decoration: none; }
</style>
