import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/app/',
  build: {
    outDir: '../src/ragrig/static/dist',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', rewrite: (p) => p.replace(/^\/api/, '') },
      '/health': 'http://localhost:8000',
      '/system': 'http://localhost:8000',
      '/knowledge-bases': 'http://localhost:8000',
      '/sources': 'http://localhost:8000',
      '/pipeline-runs': 'http://localhost:8000',
      '/models': 'http://localhost:8000',
      '/plugins': 'http://localhost:8000',
      '/retrieval': 'http://localhost:8000',
      '/answer': 'http://localhost:8000',
      '/tasks': 'http://localhost:8000',
      '/evaluations': 'http://localhost:8000',
      '/processing-profiles': 'http://localhost:8000',
      '/supported-formats': 'http://localhost:8000',
      '/sanitizer-coverage': 'http://localhost:8000',
      '/sanitizer-drift-history': 'http://localhost:8000',
      '/ops': 'http://localhost:8000',
    },
  },
})
