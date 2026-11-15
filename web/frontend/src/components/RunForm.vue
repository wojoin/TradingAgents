<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import DatePicker from 'primevue/datepicker'
import InputText from 'primevue/inputtext'
import Message from 'primevue/message'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import { useToast } from 'primevue/usetoast'
import { api, type Options, type ProviderOption, type RunSummary } from '../api'
import StockPicker from './StockPicker.vue'

// Every choice the CLI asks before a run, defaulting to the last run's answers.
const props = defineProps<{ initialTicker?: string }>()
const emit = defineEmits<{ started: [run: RunSummary] }>()
const toast = useToast()

const CUSTOM = '__custom__'
const opts = ref<Options | null>(null)
const loadError = ref('')
const starting = ref(false)

const ticker = ref(props.initialTicker || '')
const date = ref<Date | null>(null)
const analysts = ref<string[]>([])
const depth = ref(1)
const provider = ref('')
const backendUrl = ref('')
const quick = ref('')
const quickCustom = ref('')
const deep = ref('')
const deepCustom = ref('')
const effort = ref<string | null>(null)
const language = ref('English')
const languageCustom = ref('')

const spec = computed<ProviderOption | undefined>(() => opts.value?.providers.find((p) => p.key === provider.value))
const providerChoices = computed(() =>
  (opts.value?.providers || []).map((p) => ({ ...p, disabled: !p.key_set })),
)
const modelChoices = (tier: 'quick' | 'deep') =>
  computed(() => [...(spec.value?.models[tier] || []), { value: CUSTOM, label: '自定义模型名…' }])
const quickChoices = modelChoices('quick')
const deepChoices = modelChoices('deep')
const languageChoices = computed(() => [...(opts.value?.languages || []), { value: CUSTOM, label: '其他语言…' }])
const maxDate = computed(() => (opts.value ? new Date(`${opts.value.today}T00:00:00`) : new Date()))

function pickModel(saved: string | null, tier: 'quick' | 'deep') {
  const listed = spec.value?.models[tier] || []
  if (saved && listed.some((m) => m.value === saved)) return { value: saved, custom: '' }
  if (saved) return { value: CUSTOM, custom: saved }
  return listed.length ? { value: listed[0].value, custom: '' } : { value: CUSTOM, custom: '' }
}

function applyProvider(saved?: { quick: string | null; deep: string | null; url: string | null; effort: string | null }) {
  const q = pickModel(saved?.quick ?? null, 'quick')
  const d = pickModel(saved?.deep ?? null, 'deep')
  quick.value = q.value
  quickCustom.value = q.custom
  deep.value = d.value
  deepCustom.value = d.custom
  backendUrl.value = saved?.url || spec.value?.url || ''
  effort.value = saved?.effort || spec.value?.effort?.choices[0]?.value || null
}

function isoDate(d: Date | null) {
  if (!d) return opts.value?.today || ''
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

onMounted(async () => {
  try {
    const o = await api.options()
    opts.value = o
    const d = o.defaults
    date.value = new Date(`${d.date}T00:00:00`)
    analysts.value = [...d.analysts]
    depth.value = d.research_depth
    provider.value = d.llm_provider
    const known = o.languages.some((l) => l.value === d.output_language)
    language.value = known ? d.output_language : CUSTOM
    languageCustom.value = known ? '' : d.output_language
    applyProvider({ quick: d.quick_think_llm, deep: d.deep_think_llm, url: d.backend_url, effort: d.effort })
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  }
})

// Switching provider offers that provider's models and endpoint.
watch(provider, (_now, before) => {
  if (before) applyProvider()
})
watch(() => props.initialTicker, (v) => {
  if (v) ticker.value = v
})

const summary = computed(() => {
  const s = spec.value
  if (!s) return ''
  const q = quick.value === CUSTOM ? quickCustom.value : quick.value
  const d = deep.value === CUSTOM ? deepCustom.value : deep.value
  return `${s.label} · 深度 ${d || '?'} / 快速 ${q || '?'} · ${depth.value} 轮 · ${analysts.value.length} 位分析师`
})

async function start() {
  const code = ticker.value.trim()
  if (!code || !opts.value || starting.value) return
  starting.value = true
  try {
    const run = await api.startRun(code, {
      date: isoDate(date.value),
      analysts: analysts.value,
      research_depth: depth.value,
      llm_provider: provider.value,
      quick_think_llm: (quick.value === CUSTOM ? quickCustom.value : quick.value).trim() || null,
      deep_think_llm: (deep.value === CUSTOM ? deepCustom.value : deep.value).trim() || null,
      backend_url: spec.value?.url_editable ? backendUrl.value.trim() || null : null,
      output_language: (language.value === CUSTOM ? languageCustom.value : language.value).trim() || 'English',
      effort: spec.value?.effort ? effort.value : null,
    })
    toast.add({ severity: 'success', summary: '已开始分析', detail: `${run.symbol}，分析日 ${run.trade_date}`, life: 3000 })
    emit('started', run)
  } catch (e) {
    toast.add({ severity: 'error', summary: '无法开始分析', detail: e instanceof Error ? e.message : String(e), life: 8000 })
  } finally {
    starting.value = false
  }
}
</script>

<template>
  <div>
    <Message v-if="loadError" severity="error">分析选项加载失败：{{ loadError }}</Message>
    <div v-else-if="opts" class="form">
      <div class="field wide">
        <label>股票 <span class="req">*</span></label>
        <StockPicker v-model="ticker" />
        <small class="muted">代码或名称；名称会转换成代码，重名时会列出候选</small>
      </div>

      <div class="field">
        <label>分析日</label>
        <DatePicker v-model="date" :max-date="maxDate" date-format="yy-mm-dd" show-icon fluid />
        <small class="muted">默认今天；只用该日之前已公开的数据</small>
      </div>

      <div class="field">
        <label>研究深度</label>
        <SelectButton v-model="depth" :options="opts.depths" option-label="label" option-value="value" :allow-empty="false" />
        <small class="muted">{{ opts.depths.find((d) => d.value === depth)?.help }}</small>
      </div>

      <div class="field wide">
        <label>分析师 <span class="req">*</span></label>
        <div class="checks">
          <label v-for="a in opts.analysts" :key="a.value" class="check">
            <Checkbox v-model="analysts" :value="a.value" /> {{ a.label }}
          </label>
        </div>
      </div>

      <div class="field">
        <label>模型提供商</label>
        <Select v-model="provider" :options="providerChoices" option-label="label" option-value="key"
                option-disabled="disabled" filter fluid>
          <template #option="{ option }">
            <span>{{ option.label }}</span>
            <span v-if="!option.key_set" class="muted small">&nbsp;· 未设置 {{ option.key_env }}</span>
          </template>
        </Select>
        <small class="muted">API key 从 .env 读取；灰色的提供商还没有 key</small>
      </div>

      <div v-if="spec?.url_editable" class="field">
        <label>接口地址</label>
        <InputText v-model="backendUrl" placeholder="http://localhost:11434/v1" fluid />
      </div>

      <div class="field">
        <label>深度思考模型</label>
        <Select v-model="deep" :options="deepChoices" option-label="label" option-value="value" fluid />
        <InputText v-if="deep === CUSTOM" v-model="deepCustom" placeholder="模型名，如 deepseek-v4-pro" class="custom" fluid />
        <small class="muted">研究经理、投资组合经理等做决策的角色</small>
      </div>

      <div class="field">
        <label>快速思考模型</label>
        <Select v-model="quick" :options="quickChoices" option-label="label" option-value="value" fluid />
        <InputText v-if="quick === CUSTOM" v-model="quickCustom" placeholder="模型名" class="custom" fluid />
        <small class="muted">分析师、研究员、交易员等其余角色</small>
      </div>

      <div v-if="spec?.effort" class="field">
        <label>推理强度</label>
        <SelectButton v-model="effort" :options="spec.effort.choices" option-label="label" option-value="value" :allow-empty="false" />
      </div>

      <div class="field">
        <label>报告语言</label>
        <Select v-model="language" :options="languageChoices" option-label="label" option-value="value" fluid />
        <InputText v-if="language === CUSTOM" v-model="languageCustom" placeholder="如 Vietnamese" class="custom" fluid />
      </div>

      <div class="field wide actions">
        <Button label="开始分析" icon="pi pi-play" :loading="starting"
                :disabled="!ticker.trim() || !analysts.length || !spec?.key_set" @click="start" />
        <span class="muted small">{{ summary }}</span>
      </div>
    </div>
    <div v-else class="muted"><i class="pi pi-spin pi-spinner" /> 加载分析选项…</div>
  </div>
</template>

<style scoped>
.form { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px 20px; }
.field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.field.wide { grid-column: 1 / -1; }
.field > label { font-weight: 600; }
.req { color: var(--up); }
.checks { display: flex; flex-wrap: wrap; gap: 16px; }
.check { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.custom { margin-top: 4px; }
.small { font-size: 12px; }
.actions { flex-direction: row; align-items: center; gap: 16px; flex-wrap: wrap; }
</style>
