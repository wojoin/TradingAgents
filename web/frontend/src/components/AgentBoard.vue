<script setup lang="ts">
import { computed } from 'vue'
import { AGENT_LABELS, type AgentStatus } from '../api'

const props = defineProps<{ agents: Record<string, AgentStatus> }>()

const TEAMS: [string, string[]][] = [
  ['分析师团队', ['Market Analyst', 'Sentiment Analyst', 'News Analyst', 'Fundamentals Analyst']],
  ['研究团队', ['Bull Researcher', 'Bear Researcher', 'Research Manager']],
  ['交易团队', ['Trader']],
  ['风控团队', ['Aggressive Analyst', 'Conservative Analyst', 'Neutral Analyst']],
  ['组合管理', ['Portfolio Manager']],
]
const teams = computed(() =>
  TEAMS.map(([team, names]) => [team, names.filter((n) => n in props.agents)] as const).filter(([, n]) => n.length),
)
const done = computed(() => Object.values(props.agents).filter((s) => s === 'completed').length)
const total = computed(() => Object.keys(props.agents).length)
const ICON: Record<AgentStatus, string> = {
  pending: 'pi pi-circle',
  in_progress: 'pi pi-spin pi-spinner',
  completed: 'pi pi-check-circle',
}
</script>

<template>
  <div>
    <div class="muted progress">完成 {{ done }} / {{ total }}</div>
    <div v-for="[team, names] in teams" :key="team" class="team">
      <div class="team-name">{{ team }}</div>
      <div v-for="name in names" :key="name" class="agent" :class="agents[name]">
        <i :class="ICON[agents[name]]" />
        <span>{{ AGENT_LABELS[name] || name }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.progress { margin-bottom: 8px; }
.team { margin-bottom: 10px; }
.team-name { font-weight: 600; margin-bottom: 4px; }
.agent { display: flex; gap: 8px; align-items: center; padding: 2px 0 2px 4px; color: var(--muted); }
.agent.in_progress { color: #2563eb; font-weight: 600; }
.agent.completed { color: var(--text); }
.agent.completed i { color: var(--down); }
</style>
