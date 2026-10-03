// @vitest-environment node
// Store wiring end to end, in-thread (no Worker / IndexedDB in node): load a folder,
// open the golden reference, import loose files.
import { describe, expect, it } from 'vitest'
import { DEV_PHASE, dirFiles, hasDev } from './testing/nodeData'
import { useDatasetStore, useRunStore } from './stores'

const asFile = (path: string, blob: Blob) => {
  const f = new File([blob], path.split('/').pop()!)
  Object.defineProperty(f, 'webkitRelativePath', { value: path })
  return f
}

describe.skipIf(!hasDev)('stores', () => {
  it('loads a folder, creates the golden run and imports loose deliverables', async () => {
    const files = (await dirFiles(DEV_PHASE, 'phase_dev')).map((f) => asFile(f.path, f.file))
    const meta = await useDatasetStore.getState().loadFromFolder(files)
    expect(meta.id).toBe('phase_dev-2026-07')
    expect(useDatasetStore.getState()).toMatchObject({ status: 'ready', activeId: meta.id, progress: null, error: null })
    expect(useDatasetStore.getState().datasets.map((d) => d.id)).toEqual([meta.id])

    const golden = await useRunStore.getState().createGoldenRun()
    expect(useRunStore.getState()).toMatchObject({ activeId: golden.id, status: 'ready' })
    expect(golden.deliverables.close.some((r) => 'je' in r)).toBe(false)

    const loose = [new File(['{"doc_id":"API004093","decision":"POST"}\n'], 'ap.jsonl')]
    const run = await useRunStore.getState().importRun(loose, 'Solo AP')
    expect(run.present).toMatchObject({ ap: true, close: false })
    expect(useRunStore.getState().runs.map((r) => r.id)).toEqual([run.id, golden.id])
    expect(useRunStore.getState().activeId).toBe(run.id)

    useRunStore.getState().setActive(golden.id)
    await useRunStore.getState().remove(run.id)
    expect(useRunStore.getState().runs.map((r) => r.id)).toEqual([golden.id])
    expect(useRunStore.getState().activeId).toBe(golden.id)

    await useDatasetStore.getState().remove(meta.id)
    expect(useDatasetStore.getState()).toMatchObject({ activeId: null, api: null, status: 'idle', datasets: [] })
    expect(useRunStore.getState().runs).toEqual([])
  })

  it('reports import errors in the run store', async () => {
    await expect(useRunStore.getState().importRun([new File(['x'], 'notes.txt')])).rejects.toThrow(/Carga primero un dataset/)
    expect(useRunStore.getState().status).toBe('error')
  })
})
