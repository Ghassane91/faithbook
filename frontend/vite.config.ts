import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // En dev (npm run dev), on tape directement le backend.
    proxy: {
      '/api': {
        target: process.env.API_URL || 'http://localhost:8020',
        changeOrigin: true,
      },
    },
  },
})
