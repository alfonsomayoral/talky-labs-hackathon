import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiProvider } from './api'

const dataset = { id: 'ds', name: 'ds', month: '2026-07' } as unknown as Parameters<typeof apiProvider.loadRun>[1]

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('apiProvider.loadRun', () => {
  it('requests only the files the run status lists', async () => {
    vi.stubEnv('VITE_API_URL', 'http://backend.test')
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        urls.push(url)
        if (url.endsWith('/api/runs/r1')) return Response.json({ state: 'done', files: ['deliverables/ap.jsonl'] })
        return new Response('', { status: 200 })
      }),
    )
    await apiProvider.loadRun('r1', dataset).catch(() => null)
    expect(urls.filter((u) => u.includes('/files/'))).toEqual(['http://backend.test/api/runs/r1/files/deliverables/ap.jsonl'])
  })
})
