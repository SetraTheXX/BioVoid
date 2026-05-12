import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/atlas': 'http://127.0.0.1:8000',
      '/protein': 'http://127.0.0.1:8000',
      '/jobs': 'http://127.0.0.1:8000',
      '/artifacts': 'http://127.0.0.1:8000',
      '/benchmark': 'http://127.0.0.1:8000',
      '/ops': 'http://127.0.0.1:8000',
      '/export': 'http://127.0.0.1:8000',
    },
  },
})
