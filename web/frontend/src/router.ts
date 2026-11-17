import { createRouter, createWebHistory } from 'vue-router'

// Each page loads on first visit, so the chart library ships only with the pages that draw one.
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/watchlist' },
    { path: '/watchlist', name: 'watchlist', component: () => import('./views/WatchlistView.vue') },
    { path: '/stock/:code?', name: 'stock', component: () => import('./views/StockView.vue'), props: true },
    { path: '/market', name: 'market', component: () => import('./views/MarketView.vue') },
    { path: '/analysis', name: 'analysis', component: () => import('./views/AnalysisView.vue') },
    { path: '/guide', name: 'guide', component: () => import('./views/GuideView.vue') },
    { path: '/reports', redirect: '/analysis' },
    { path: '/reports/:id', name: 'report', component: () => import('./views/ReportView.vue'), props: true },
  ],
})
