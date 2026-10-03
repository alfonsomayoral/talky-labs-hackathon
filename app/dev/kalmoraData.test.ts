// @vitest-environment node
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { createServer, request, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { createKalmoraHandler } from './kalmoraData.ts'

let root: string
let server: Server
let base: string

beforeAll(async () => {
  root = mkdtempSync(join(tmpdir(), 'kalmora-data-'))
  const phase = join(root, 'phase_x')
  mkdirSync(join(phase, 'erp'), { recursive: true })
  mkdirSync(join(phase, 'tasks'), { recursive: true })
  mkdirSync(join(phase, 'bank', 'BIN-1'), { recursive: true })
  writeFileSync(join(phase, 'erp', 'vendors.jsonl'), '{"id":"V1"}\n')
  writeFileSync(join(phase, 'tasks', 'close.json'), '{"month":"2026-07","steps":[]}')
  writeFileSync(join(phase, 'bank', 'BIN-1', '2026-07.n43'), '11...\r\n')
  writeFileSync(join(phase, '.DS_Store'), 'x')
  writeFileSync(join(root, 'secret.txt'), 'nope')
  const runs = join(root, 'runs')
  mkdirSync(join(runs, 'r1', 'deliverables'), { recursive: true })
  writeFileSync(join(runs, 'r1', 'deliverables', 'ap.jsonl'), '{"doc_id":"A"}\n')
  mkdirSync(join(runs, 'loose'), { recursive: true })
  writeFileSync(join(runs, 'loose', 'ic.jsonl'), '')
  mkdirSync(join(runs, 'not-a-run'), { recursive: true })

  const handler = createKalmoraHandler(
    { datasets: 'x:phase_x, missing:does_not_exist', runs: 'runs' },
    root,
  )
  server = createServer((req, res) => handler(req, res, () => ((res.statusCode = 404), res.end('next'))))
  await new Promise<void>((ok) => server.listen(0, '127.0.0.1', ok))
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
})

afterAll(async () => {
  await new Promise((ok) => server.close(ok))
  rmSync(root, { recursive: true, force: true })
})

// fetch() normalizes `..` away; a raw request keeps the path as sent.
const rawGet = (path: string) =>
  new Promise<{ status: number; body: string }>((ok, ko) => {
    const req = request(`${base}${path}`, { path }, (res) => {
      let body = ''
      res.on('data', (c) => (body += c))
      res.on('end', () => ok({ status: res.statusCode ?? 0, body }))
    })
    req.on('error', ko)
    req.end()
  })

describe('kalmoraData middleware', () => {
  it('lists existing datasets only', async () => {
    const res = await fetch(`${base}/__data`)
    expect(await res.json()).toEqual([{ id: 'x', name: 'phase_x', path: 'phase_x' }])
  })

  it('serves a recursive index without hidden files', async () => {
    const index = (await (await fetch(`${base}/__data/x/__index.json`)).json()) as { path: string; size: number }[]
    expect(index.map((e) => e.path)).toEqual(['bank/BIN-1/2026-07.n43', 'erp/vendors.jsonl', 'tasks/close.json'])
    expect(index[1].size).toBe(12)
  })

  it('serves files with content types', async () => {
    const jsonl = await fetch(`${base}/__data/x/erp/vendors.jsonl`)
    expect(jsonl.headers.get('content-type')).toContain('application/x-ndjson')
    expect(await jsonl.text()).toBe('{"id":"V1"}\n')
    const n43 = await fetch(`${base}/__data/x/bank/BIN-1/2026-07.n43`)
    expect(n43.headers.get('content-type')).toBe('text/plain')
    expect((await fetch(`${base}/__data/x/erp/nope.jsonl`)).status).toBe(404)
  })

  it('never serves files outside the roots', async () => {
    for (const path of ['/__data/x/../secret.txt', '/__data/x/%2E%2E/secret.txt', '/__runs/r1/../../secret.txt']) {
      const res = await rawGet(path)
      expect(res.status).not.toBe(200)
      expect(res.body).not.toContain('nope')
    }
    expect((await rawGet('/__data/x/erp/..%2F..%2F..%2Fsecret.txt')).status).toBe(403)
    expect((await rawGet('/__runs/..%2F/__index.json')).status).toBe(403)
  })

  it('lists run bundles and serves their files', async () => {
    const runs = (await (await fetch(`${base}/__runs`)).json()) as { id: string }[]
    expect(runs.map((r) => r.id).sort()).toEqual(['loose', 'r1'])
    const index = await (await fetch(`${base}/__runs/r1/__index.json`)).json()
    expect(index).toEqual([{ path: 'deliverables/ap.jsonl', size: 15 }])
    expect(await (await fetch(`${base}/__runs/r1/deliverables/ap.jsonl`)).text()).toBe('{"doc_id":"A"}\n')
  })

  it('answers empty lists for missing folders and passes other urls through', async () => {
    const handler = createKalmoraHandler({ datasets: '', runs: 'nowhere' }, root)
    const local = createServer((req, res) => handler(req, res, () => ((res.statusCode = 404), res.end('next'))))
    await new Promise<void>((ok) => local.listen(0, '127.0.0.1', ok))
    const url = `http://127.0.0.1:${(local.address() as AddressInfo).port}`
    expect(await (await fetch(`${url}/__data`)).json()).toEqual([])
    expect(await (await fetch(`${url}/__runs`)).json()).toEqual([])
    expect(await (await fetch(`${url}/src/main.tsx`)).text()).toBe('next')
    await new Promise((ok) => local.close(ok))
  })
})
