import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const target = 'http://localhost:8000'
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/sim': target,
      '/intake': target,
      '/patients': target,
      '/ws': { target, ws: true },
    },
  },
})
