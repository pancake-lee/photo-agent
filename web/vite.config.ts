import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 10006,
    proxy: {
      '/api/chat': {
        target: 'http://localhost:10005',
        changeOrigin: true,
      },
      '/api/embed': {
        target: 'http://localhost:10005',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:10004',
        changeOrigin: true,
      },
    },
  },
})
