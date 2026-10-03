import { fileURLToPath, URL } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import { assistantChat } from './dev/assistantChat.ts'
import { kalmoraData } from './dev/kalmoraData.ts'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [
      react(),
      kalmoraData({ datasets: env.KALMORA_DATASETS, runs: env.KALMORA_RUNS }),
      assistantChat({ apiKey: env.OPENAI_API_KEY, projectId: env.OPENAI_PROJECT_ID, model: env.OPENAI_MODEL }),
    ],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    worker: { format: 'es' },
  }
})
