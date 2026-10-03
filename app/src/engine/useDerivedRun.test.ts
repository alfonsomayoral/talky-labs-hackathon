import { act, renderHook, waitFor } from '@testing-library/react'
import { create } from 'zustand'
import type { DatasetApi, RunBundle, TrialBalanceRow } from '@/domain/types'
import { devPhase, goldenRun, loadCore, loadGolden } from './test-utils/phase'
import { useAttention, useDerivedRun, useItem } from './useDerivedRun'

// Minimal stand-ins for the data stores: only the fields the hook reads.
const stores = vi.hoisted(() => ({ dataset: null as unknown, run: null as unknown }))
vi.mock('@/data/stores', () => {
  stores.dataset = create(() => ({ api: null as DatasetApi | null, status: 'idle', error: null }))
  stores.run = create(() => ({ runs: [] as RunBundle[], activeId: null as string | null, status: 'idle', error: null }))
  return { useDatasetStore: stores.dataset, useRunStore: stores.run }
})

type Store<T> = { setState(s: Partial<T>): void }
const datasetStore = () => stores.dataset as Store<{ api: DatasetApi | null; status: string }>
const runStore = () => stores.run as Store<{ runs: RunBundle[]; activeId: string | null }>

const fixture = await devPhase()

describe.skipIf(!fixture)('useDerivedRun', () => {
  it('derives the active run and fills the trial balance when the journal sum arrives', async () => {
    const golden = loadGolden(fixture!)
    const core = loadCore(fixture!, golden)
    const run = goldenRun(golden)
    let resolveTb: (rows: TrialBalanceRow[]) => void = () => {}
    const recordedTrialBalance = vi.fn(() => new Promise<TrialBalanceRow[]>((r) => (resolveTb = r)))
    const api = { meta: { id: 'dev' }, core, recordedTrialBalance } as unknown as DatasetApi

    const { result } = renderHook(() => ({ state: useDerivedRun(), item: useItem('ap:API004128'), attention: useAttention() }))
    expect(result.current.state.status).toBe('idle')

    act(() => {
      datasetStore().setState({ api, status: 'ready' })
      runStore().setState({ runs: [run], activeId: run.id })
    })
    expect(result.current.state.status).toBe('ready')
    expect(result.current.state.data?.score?.total).toBe(100)
    expect(result.current.state.data?.trialBalance).toBeNull()
    expect(result.current.item?.outcome).toBe('POST')
    expect(result.current.attention.length).toBeGreaterThan(0)
    const first = result.current.state.data

    act(() => resolveTb(golden.trialBalanceRecorded))
    await waitFor(() => expect(result.current.state.data?.trialBalance?.gapAfter).toBe(0))
    expect(result.current.state.data?.items).toBe(first?.items)
    expect(recordedTrialBalance).toHaveBeenCalledTimes(1)
  })
})
