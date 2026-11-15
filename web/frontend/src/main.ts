import { createApp } from 'vue'
import PrimeVue from 'primevue/config'
import ToastService from 'primevue/toastservice'
import Aura from '@primeuix/themes/aura'
import 'primeicons/primeicons.css'
import './style.css'
import App from './App.vue'
import { router } from './router'

createApp(App)
  .use(router)
  // Light theme only: the dark selector is a class the app never sets.
  .use(PrimeVue, { theme: { preset: Aura, options: { darkModeSelector: '.app-dark' } } })
  .use(ToastService)
  .mount('#app')
