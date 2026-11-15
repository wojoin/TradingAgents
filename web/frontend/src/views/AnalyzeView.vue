<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import Tabs from 'primevue/tabs'
import TabList from 'primevue/tablist'
import Tab from 'primevue/tab'
import TabPanels from 'primevue/tabpanels'
import TabPanel from 'primevue/tabpanel'
import { useToast } from 'primevue/usetoast'
import { api, RUN_STATUS, ratingSeverity, type AgentStatus, type RunSummary, type Settings } from '../api'
import AgentBoard from '../components/AgentBoard.vue'
import MarkdownView from '../components/MarkdownView.vue'
import DownloadButtons from '../components/DownloadButtons.vue'

const toast = useToast()
const ticker = ref('')
const starting = ref(false)
const settings = ref<Settings | null>(null)
const runs = ref<RunSummary[]>([])
const current = ref<RunSummary | null>(null)
const agents = ref<Record<string, AgentStatus>>({})
const sections = ref<Record<string, { title: string; content: string }>>({})
const tools = ref<{ name: string; at: string }[]>([])
const activeTab = ref<string>('')
let source: EventSource | null = null

const sectionKeys = computed(() => Object.keys(sections.value))
const errorText = computed(() => current.value?.error || '')

async function loadRuns() {
  runs.value = await api.runs()
}

async function start() {
  const code = ticker.value.trim()
  if (!code) return
  starting.value = true
  try {
    const run = await api.startRun(code)
    toast.add({ severity: 'success', summary: '已开始分析', detail: `${run.symbol}，分析日 ${run.trade_date}`, life: 3000 })
    ticker.value = ''
    await loadRuns()
    follow(run)
  } catch (e) {
    toast.add({ severity: 'error', summary: '无法开始分析', detail: e instanceof Error ? e.message : String(e), life: 6000 })
  } finally {
    starting.value = false
  }
}

function follow(run: RunSummary) {
  source?.close()
  current.value = { ...run }
  agents.value = {}
  sections.value = {}
  tools.value = []
  activeTab.value = ''
  source = api.events(run.id)
  const parse = (e: Event) => JSON.parse((e as MessageEvent).data)
  source.addEventListener('status', (e) => {
    const { status } = parse(e)
    if (current.value) current.value.status = status
    if (status === 'completed' || status === 'failed') {
      source?.close()
      loadRuns()
    }
  })
  source.addEventListener('agent', (e) => {
    const { agent, status } = parse(e)
    agents.value = { ...agents.value, [agent]: status }
  })
  source.addEventListener('section', (e) => {
    const { key, title, content } = parse(e)
    sections.value = { ...sections.value, [key]: { title, content } }
    activeTab.value = key
  })
  source.addEventListener('tool', (e) => {
    tools.value = [{ name: parse(e).name, at: new Date().toLocaleTimeString() }, ...tools.value].slice(0, 12)
  })
  source.addEventListener('done', (e) => {
    const { report_id, rating } = parse(e)
    if (current.value) Object.assign(current.value, { report_id, rating })
    toast.add({ severity: 'success', summary: '分析完成', detail: `评级 ${rating}`, life: 5000 })
  })
  source.addEventListener('error', (e) => {
    // A server 'error' event carries data; a dropped connection does not (EventSource reconnects).
    const data = (e as MessageEvent).data
    if (data && current.value) current.value.error = JSON.parse(data).message
  })
}

onMounted(async () => {
  settings.value = await api.settings().catch(() => null)
  await loadRuns()
  const active = runs.value.find((r) => r.status === 'running' || r.status === 'queued') || runs.value[0]
  if (active) follow(active)
})
onBeforeUnmount(() => source?.close())
</script>

<template>
  <div class="page">
    <div class="card start">
      <div class="row">
        <InputText v-model="ticker" placeholder="股票代码，如 300308" class="ticker" @keyup.enter="start" />
        <Button label="开始分析" icon="pi pi-play" :loading="starting" :disabled="!ticker.trim()" @click="start" />
      </div>
      <div v-if="settings" class="muted settings">
        模型 {{ settings.llm_provider }} · {{ settings.deep_think_llm }} / {{ settings.quick_think_llm }} ·
        辩论 {{ settings.research_rounds }} 轮 / 风控 {{ settings.risk_rounds }} 轮 · 输出 {{ settings.output_language }}
        <span v-if="!settings.prefs_found">（未找到 CLI 的上次设置，使用默认配置）</span>
      </div>
    </div>

    <div class="layout">
      <aside class="card">
        <div class="side-title">本次启动的任务</div>
        <div v-if="!runs.length" class="muted">还没有任务。输入股票代码开始一次分析。</div>
        <button v-for="r in runs" :key="r.id" class="run" :class="{ active: current?.id === r.id }" @click="follow(r)">
          <div class="row between">
            <strong>{{ r.symbol }}</strong>
            <Tag :value="RUN_STATUS[r.status].label" :severity="RUN_STATUS[r.status].severity" />
          </div>
          <div class="muted small">{{ r.trade_date }} · {{ r.created.replace('T', ' ') }}</div>
        </button>
      </aside>

      <section v-if="current" class="main">
        <div class="card">
          <div class="row between">
            <div class="row">
              <h2 class="title">{{ current.symbol }}</h2>
              <Tag :value="RUN_STATUS[current.status].label" :severity="RUN_STATUS[current.status].severity" />
              <Tag v-if="current.rating" :value="`评级 ${current.rating}`" :severity="ratingSeverity(current.rating)" />
            </div>
            <div v-if="current.report_id" class="row">
              <RouterLink :to="`/reports/${current.report_id}`"><Button label="查看报告" icon="pi pi-eye" text /></RouterLink>
              <DownloadButtons :report-id="current.report_id" size="small" />
            </div>
          </div>
          <Message v-if="errorText" severity="error" class="err">{{ errorText }}</Message>
        </div>

        <div class="grid">
          <div class="card">
            <AgentBoard :agents="agents" />
            <div v-if="tools.length" class="tools">
              <div class="team-name">最近的工具调用</div>
              <div v-for="(t, i) in tools" :key="i" class="muted small">{{ t.at }} · {{ t.name }}</div>
            </div>
          </div>
          <div class="card reports">
            <div v-if="!sectionKeys.length" class="muted waiting">
              <i class="pi pi-spin pi-spinner" v-if="current.status === 'running'" />
              {{ current.status === 'queued' ? '排队中，等前一个任务结束' : '分析师正在工作，报告写好后会出现在这里' }}
            </div>
            <Tabs v-else v-model:value="activeTab" scrollable>
              <TabList>
                <Tab v-for="key in sectionKeys" :key="key" :value="key">{{ sections[key].title }}</Tab>
              </TabList>
              <TabPanels>
                <TabPanel v-for="key in sectionKeys" :key="key" :value="key">
                  <MarkdownView :source="sections[key].content" />
                </TabPanel>
              </TabPanels>
            </Tabs>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.start { margin-bottom: 16px; }
.ticker { width: 260px; max-width: 100%; }
.settings { margin-top: 10px; font-size: 13px; }
.layout { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 16px; align-items: start; }
.side-title, .team-name { font-weight: 600; margin-bottom: 8px; }
.run { display: block; width: 100%; text-align: left; background: none; border: 1px solid transparent; border-radius: 8px; padding: 8px; cursor: pointer; font: inherit; color: inherit; }
.run:hover { background: #f6f7f9; }
.run.active { border-color: #2563eb; background: #eff4ff; }
.between { justify-content: space-between; }
.small { font-size: 12px; }
.main { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.title { margin: 0; font-size: 20px; }
.err { margin-top: 12px; }
.grid { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 16px; align-items: start; }
.tools { margin-top: 12px; border-top: 1px solid var(--border); padding-top: 10px; }
.reports { min-height: 320px; }
.waiting { padding: 32px 0; text-align: center; }
@media (max-width: 900px) {
  .layout, .grid { grid-template-columns: 1fr; }
}
</style>
