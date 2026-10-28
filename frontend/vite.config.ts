import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const hmrPort = env.WDS_SOCKET_PORT ? Number(env.WDS_SOCKET_PORT) : undefined

  return {
    plugins: [react()],
    envPrefix: ['VITE_', 'REACT_APP_'],
    server: {
      allowedHosts: true,
      hmr: hmrPort ? { clientPort: hmrPort } : undefined,
    },
  }
})
