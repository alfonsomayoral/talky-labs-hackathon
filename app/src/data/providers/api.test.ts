import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiProvider } from './api'

const dataset = { id: 'ds', name: 'ds', month: '2026-07' } as unknown as Parameters<typeof apiProvider.loadRun>[1]

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

const backend = (routes: Record<string, unknown>) => {
  const urls: string[] = []
  vi.stubEnv('VITE_API_URL', 'http://backend.test/')
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      urls.push(url)
      const path = url.replace('http://backend.test', '')
      if (!(path in routes)) return new Response('', { status: 404 })
      const body = routes[path]
      return typeof body === 'string' ? new Response(body) : Response.json(body)
    }),
  )
  return urls
}

describe('apiProvider (/v1)', () => {
  it('lists loaded phases as datasets', async () => {
    backend({ '/v1/phases': { data: [{ phase: 'phase_test', month: '2026-09' }] } })
    expect(await apiProvider.listDatasets()).toEqual([{ id: 'phase_test', name: 'phase_test · 2026-09' }])
  })

  it('lists only runs that have a bundle', async () => {
    backend({
      '/v1/runs?limit=1000': {
        data: { items: [{ run_id: 'aaaaaaaa-1', started_at: '2026-10-03T15:00:00', has_files: true }, { run_id: 'bbbbbbbb-2', has_files: false }] },
      },
    })
    expect(await apiProvider.listRuns(dataset)).toEqual([{ id: 'aaaaaaaa-1', label: 'aaaaaaaa · 2026-10-03 15:00' }])
  })

  it('loads the bundle files and uses the run report as manifest when the bundle has none', async () => {
    const urls = backend({
      '/v1/runs/r1/files/__index.json': [{ path: 'deliverables/ap.jsonl' }, { path: 'notes.txt' }],
      '/v1/runs/r1/files/deliverables/ap.jsonl': '{"doc_id":"API1","decision":"POST"}\n',
      '/v1/runs/r1': { data: { run_id: 'r1', status: 'completed', calls: [] } },
    })
    await apiProvider.loadRun('r1', dataset).catch(() => null)
    expect(urls).toContain('http://backend.test/v1/runs/r1/files/deliverables/ap.jsonl')
    expect(urls).toContain('http://backend.test/v1/runs/r1')
    expect(urls.some((u) => u.endsWith('notes.txt'))).toBe(false)
  })
})

describe('apiProvider (/v1) closes and uploads', () => {
  it('lists only runs of the dataset month', async () => {
    backend({
      '/v1/runs?limit=1000': {
        data: { items: [{ run_id: 'aaaaaaaa-1', month: '2026-07', has_files: true, status: 'running' }, { run_id: 'cccccccc-3', month: '2026-09', has_files: true }] },
      },
    })
    expect(await apiProvider.listRuns(dataset)).toEqual([{ id: 'aaaaaaaa-1', label: 'aaaaaaaa · en curso' }])
  })

  it('launches a close on the dataset phase and reports done when the run completes', async () => {
    const urls = backend({ '/v1/phases/phase_test/runs': { data: { run_id: 'r9' } }, '/v1/runs/r9': { data: { status: 'completed' } } })
    expect(await apiProvider.startRun!({ ...dataset, remoteId: 'phase_test' })).toBe('r9')
    const events = await new Promise<string[]>((resolve) => {
      const seen: string[] = []
      apiProvider.subscribeRun!('r9', (e) => resolve([...seen, e.type]))
    })
    expect(events).toEqual(['done'])
    expect(urls).toContain('http://backend.test/v1/phases/phase_test/runs')
  })

  it('uploads a package and resolves with the phases the job loaded', async () => {
    backend({
      '/v1/packages': { data: { package_id: 'p1', job_id: 'j1', already_registered: false } },
      '/v1/jobs/j1': { data: { status: 'loaded', phases: [{ phase: 'phase_test' }] } },
    })
    expect(await apiProvider.uploadDataset!(new File(['zip'], 'sept.zip'))).toEqual(['phase_test'])
  })
})
