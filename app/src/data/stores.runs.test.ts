// @vitest-environment node
// Runs of a dataset that is not open live only in the browser's storage (here an in-memory map).
import { describe, expect, it, vi } from 'vitest'
import type { RunBundle } from '@/domain/types'
import { useRunStore } from './stores'

const kv = vi.hoisted(() => new Map<string, unknown>())
vi.mock('./persist', () => ({
  persistenceAvailable: () => true,
  loadDatasets: async () => [],
  saveDatasets: async () => undefined,
  loadOrigin: async () => null,
  saveOrigin: async () => undefined,
  loadRuns: async (id: string) => (kv.get(`runs:${id}`) as RunBundle[] | undefined) ?? [],
  saveRuns: async (id: string, runs: RunBundle[]) => void kv.set(`runs:${id}`, runs),
  loadSession: async () => ({ datasetId: null, runs: {} }),
  saveSession: async () => undefined,
  forgetDataset: async () => undefined,
}))

const run = (id: string) => ({ id, datasetId: 'other', label: id }) as RunBundle

describe('runs of a dataset that is not open', () => {
  it('lists them and removes one without opening the dataset', async () => {
    kv.set('runs:other', [run('r1'), run('r2')])
    expect((await useRunStore.getState().runsOf('other')).map((r) => r.id)).toEqual(['r1', 'r2'])

    await useRunStore.getState().remove('r1', 'other')
    expect((await useRunStore.getState().runsOf('other')).map((r) => r.id)).toEqual(['r2'])
    expect(useRunStore.getState().runs).toEqual([])
  })
})
