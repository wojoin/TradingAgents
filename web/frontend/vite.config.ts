import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// In development the page runs on Vite (5173) and the API on uvicorn (8765, or TA_API_PORT).
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: { '/api': { target: `http://127.0.0.1:${process.env.TA_API_PORT || 8765}`, changeOrigin: false } },
  },
})
