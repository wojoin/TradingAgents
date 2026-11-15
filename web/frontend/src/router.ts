import { createRouter, createWebHistory } from 'vue-router'

// Each page loads on first visit, so the chart library ships only with the report page.
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'analyze', component: () => import('./views/AnalyzeView.vue') },
    { path: '/reports', name: 'reports', component: () => import('./views/ReportsView.vue') },
    { path: '/reports/:id', name: 'report', component: () => import('./views/ReportView.vue'), props: true },
  ],
})
