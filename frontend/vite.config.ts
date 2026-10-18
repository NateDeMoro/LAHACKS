import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => {
  // BACKEND_URL lets a second worktree point at its own backend port.
  const target = loadEnv(mode, '.', '').BACKEND_URL ?? 'http://localhost:8000'
  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        '/sim': target,
        '/intake': target,
        '/patients': target,
        '/ws': { target, ws: true },
      },
    },
  }
})
