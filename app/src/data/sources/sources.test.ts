// @vitest-environment node
import { strToU8, zipSync } from 'fflate'
import { describe, expect, it } from 'vitest'
import { DEV_PHASE, dirFiles, hasDev } from '../testing/nodeData'
import { fileSystemSource, pathFiles } from './fileSystemSource'
import { detectPhaseRoots } from './root'
import { zipSource } from './zipSource'

const fileAt = (path: string, content: string) => {
  const f = new File([content], path.split('/').pop()!)
  Object.defineProperty(f, 'webkitRelativePath', { value: path })
  return f
}

describe('phase root detection', () => {
  it('finds the folder holding erp/ and tasks/ at any depth, shallowest first', () => {
    expect(detectPhaseRoots(['phase_dev/erp/a.jsonl', 'phase_dev/tasks/close.json'])).toEqual(['phase_dev'])
    expect(detectPhaseRoots(['erp/a.jsonl', 'tasks/close.json'])).toEqual([''])
    expect(detectPhaseRoots(['Talky/participant-2/phase_test/erp/a', 'Talky/participant-2/phase_test/tasks/b', 'Talky/participant/phase_dev/erp/a', 'Talky/participant/phase_dev/tasks/b'])).toEqual([
      'Talky/participant-2/phase_test',
      'Talky/participant/phase_dev',
    ])
    expect(detectPhaseRoots(['phase/erp/a.jsonl', 'phase/inbox/x'])).toEqual([])
  })
})

describe('FileSystemSource from File objects', () => {
  it('maps webkitRelativePath to phase-relative paths and skips junk', async () => {
    const files = [
      fileAt('participant/phase_dev/erp/vendors.jsonl', '{"id":"V1"}\n'),
      fileAt('participant/phase_dev/tasks/close.json', '{"month":"2026-07"}'),
      fileAt('participant/phase_dev/.DS_Store', 'x'),
      fileAt('participant/README.md', '# readme'),
      fileAt('participant/__pycache__/score.pyc', 'x'),
    ]
    const src = fileSystemSource(pathFiles(files))
    expect(src.name).toBe('phase_dev')
    expect((await src.list()).map((f) => f.path).sort()).toEqual(['erp/vendors.jsonl', 'tasks/close.json'])
    expect(await src.text('tasks/close.json')).toBe('{"month":"2026-07"}')
    await expect(src.read('README.md')).rejects.toThrow(/No existe/)
  })

  it('rejects a selection without a phase', () => {
    expect(() => fileSystemSource(pathFiles([fileAt('x/inbox/a.pdf', '')]))).toThrow(/erp\/ y tasks\//)
  })

  it.skipIf(!hasDev)('reads real files through File objects built from disk', async () => {
    const files = (await dirFiles(`${DEV_PHASE}/tasks`, 'phase_dev/tasks')).concat(await dirFiles(`${DEV_PHASE}/erp`, 'phase_dev/erp'))
    const asFiles = await Promise.all(files.map(async (f) => fileAt(f.path, await f.file.text())))
    const src = fileSystemSource(pathFiles(asFiles.filter((f) => !f.name.startsWith('journal') && !f.name.startsWith('goods'))))
    expect(JSON.parse(await src.text('tasks/close.json')).month).toBe('2026-07')
  })
})

describe('ZipSource', () => {
  it('detects the root inside the zip and decompresses on demand', async () => {
    const zip = zipSync({
      'kalmora/phase_dev/erp/vendors.jsonl': strToU8('{"id":"V1"}\n'),
      'kalmora/phase_dev/tasks/close.json': strToU8('{"month":"2026-07","steps":[]}'),
      '__MACOSX/kalmora/phase_dev/erp/._vendors.jsonl': strToU8('junk'),
    })
    const src = await zipSource(new Blob([zip]), 'entrega.zip')
    expect(src.kind).toBe('zip')
    expect(src.name).toBe('phase_dev')
    expect(await src.list()).toEqual([
      { path: 'erp/vendors.jsonl', size: 12 },
      { path: 'tasks/close.json', size: 30 },
    ])
    expect(await src.text('erp/vendors.jsonl')).toBe('{"id":"V1"}\n')
  })

  it('uses the zip name when the phase is at the zip root', async () => {
    const zip = zipSync({ 'erp/a.jsonl': strToU8(''), 'tasks/close.json': strToU8('{}') })
    expect((await zipSource(new Blob([zip]), 'julio.zip')).name).toBe('julio')
  })
})
