import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        // Mol* has intentional internal re-export cycles. Keeping its graph in
        // one lazy chunk avoids Rollup splitting the cycle across chunks.
        manualChunks(id) {
          if (id.includes('/node_modules/molstar/')) return 'molstar';
          return undefined;
        },
      },
    },
  },
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
