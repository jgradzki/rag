import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Forward API calls to the FastAPI backend during development.
    // API_URL lets a second dev server point at another backend (used by the /test skill).
    proxy: {
      '/api': process.env.API_URL ?? 'http://localhost:8000',
    },
  },
})
