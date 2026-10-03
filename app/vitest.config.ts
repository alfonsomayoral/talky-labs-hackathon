import { fileURLToPath, URL } from 'node:url'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

// Data-backed tests read the dataset paths from .env.local (KALMORA_DATASETS), so they
// work from any worktree; explicit KALMORA_DEV_PHASE / KALMORA_TEST_PHASE win.
const datasets = Object.fromEntries(
  (loadEnv('test', process.cwd(), '').KALMORA_DATASETS ?? '')
    .split(',')
    .map((pair) => pair.split(':').map((s) => s.trim()))
    .filter((p) => p.length === 2 && p[0] && p[1]),
)

export default defineConfig({
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', 'dev/**/*.test.ts'],
    testTimeout: 120_000,
    passWithNoTests: true,
    env: {
      ...(datasets.dev && !process.env.KALMORA_DEV_PHASE ? { KALMORA_DEV_PHASE: datasets.dev } : {}),
      ...(datasets.test && !process.env.KALMORA_TEST_PHASE ? { KALMORA_TEST_PHASE: datasets.test } : {}),
    },
  },
})
