import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// The UI talks to the existing FastAPI backend through a same-origin proxy (the backend has no CORS
// configuration, by design). HMS_API_TARGET selects the backend, e.g. http://127.0.0.1:8000 (default).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.HMS_API_TARGET || 'http://127.0.0.1:8000'
  const proxy = { target, changeOrigin: false }
  return {
    plugins: [react()],
    server: { port: 5173, strictPort: true, proxy: { '/api': proxy, '/health': proxy } },
    preview: { port: 4173, strictPort: true, proxy: { '/api': proxy, '/health': proxy } },
  }
})
