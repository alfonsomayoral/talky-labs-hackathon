// ⌘K entity search: items, vendors, customers, accounts and bank lines by id or name.
// Detail pages live in the data explorer (4.A): /datos/<entity>/<id>.
import type { BankLine, ChartAccount, Customer, JournalEntry, TaskKey, Vendor, WorkItem } from '@/domain/types'

export const TASK_ROUTE: Record<TaskKey, string> = {
  ap: '/tareas/ap',
  ar_billing: '/tareas/facturacion',
  ar_cash: '/tareas/cobros',
  bank_rec: '/tareas/bancos',
  ic: '/tareas/intragrupo',
  close: '/tareas/cierre',
}

const TASK_LABEL: Record<TaskKey, string> = {
  ap: 'Bandeja AP',
  ar_billing: 'Facturación',
  ar_cash: 'Cobros',
  bank_rec: 'Bancos',
  ic: 'Intragrupo',
  close: 'Cierre',
}

export const explorerRoute = {
  vendor: (id: string) => `/datos/proveedores/${encodeURIComponent(id)}`,
  customer: (id: string) => `/datos/clientes/${encodeURIComponent(id)}`,
  account: (account: string) => `/datos/cuentas/${encodeURIComponent(account)}`,
  journal: (entryId: string) => `/datos/diario/${encodeURIComponent(entryId)}`,
  statement: (account: string, month: string) => `/datos/extractos/${encodeURIComponent(account)}/${encodeURIComponent(month)}`,
}

export type SearchTarget = { kind: 'item'; itemId: string; task: TaskKey } | { kind: 'route'; to: string }

export interface SearchHit {
  id: string
  group: string
  label: string
  hint?: string
  target: SearchTarget
}

export interface SearchSources {
  vendors: Pick<Vendor, 'id' | 'name' | 'tax_id'>[]
  customers: Pick<Customer, 'id' | 'name' | 'tax_id'>[]
  chartOfAccounts: Pick<ChartAccount, 'account' | 'description'>[]
  bankStatements: { account: string; month: string; lines: Pick<BankLine, 'bank_line' | 'text'>[] }[]
}

export type SearchItem = Pick<WorkItem, 'id' | 'task' | 'key' | 'title' | 'company' | 'evidence'>

interface Entry {
  hit: SearchHit
  terms: string[]
  rank: number
}

export const GROUPS = ['Partidas', 'Proveedores', 'Clientes', 'Cuentas', 'Líneas bancarias', 'Asientos'] as const
const PER_GROUP = 5
const MIN_QUERY = 2

export function normalize(text: string): string {
  return text.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase().trim()
}

function itemTerms(item: SearchItem): string[] {
  const terms = [item.key, ...item.key.split('/')]
  for (const e of item.evidence) {
    if (e.kind === 'bank') terms.push(e.bank_line)
    else if (e.kind === 'journal') terms.push(e.book_line.split('#')[0])
  }
  return terms
}

export function buildEntityIndex(sources: SearchSources, items: readonly SearchItem[]): Entry[] {
  const entries: Omit<Entry, 'rank'>[] = []
  const add = (hit: SearchHit, terms: string[]) => entries.push({ hit, terms: [...new Set(terms.filter(Boolean).map(normalize))] })

  for (const item of items) {
    add(
      {
        id: item.id,
        group: 'Partidas',
        label: `${item.key} · ${item.title}`,
        hint: [TASK_LABEL[item.task], item.company].filter(Boolean).join(' · '),
        target: { kind: 'item', itemId: item.id, task: item.task },
      },
      itemTerms(item),
    )
  }
  for (const v of sources.vendors) {
    add({ id: `vendor:${v.id}`, group: 'Proveedores', label: v.name, hint: v.id, target: { kind: 'route', to: explorerRoute.vendor(v.id) } }, [v.id, v.name, v.tax_id])
  }
  for (const c of sources.customers) {
    add({ id: `customer:${c.id}`, group: 'Clientes', label: c.name, hint: c.id, target: { kind: 'route', to: explorerRoute.customer(c.id) } }, [c.id, c.name, c.tax_id])
  }
  for (const a of sources.chartOfAccounts) {
    add(
      { id: `account:${a.account}`, group: 'Cuentas', label: `${a.account} · ${a.description}`, target: { kind: 'route', to: explorerRoute.account(a.account) } },
      [a.account, a.description],
    )
  }
  for (const s of sources.bankStatements) {
    for (const l of s.lines) {
      add(
        {
          id: `bank:${s.account}/${l.bank_line}`,
          group: 'Líneas bancarias',
          label: `${l.bank_line} · ${l.text}`,
          hint: `${s.account} · ${s.month}`,
          target: { kind: 'route', to: explorerRoute.statement(s.account, s.month) },
        },
        [l.bank_line],
      )
    }
  }
  return entries.map((e) => ({ ...e, rank: GROUPS.indexOf(e.hit.group as (typeof GROUPS)[number]) }))
}

function score(terms: string[], q: string): number {
  let best = 0
  for (const t of terms) {
    if (t === q) return 3
    if (t.startsWith(q)) best = Math.max(best, 2)
    else if (best === 0 && t.includes(q)) best = 1
  }
  return best
}

/** Best matches first (exact id › prefix › substring), at most 5 per group. */
export function searchEntities(index: readonly Entry[], query: string): SearchHit[] {
  const q = normalize(query)
  if (q.length < MIN_QUERY) return []
  const matches: { entry: Entry; score: number; i: number }[] = []
  index.forEach((entry, i) => {
    const s = score(entry.terms, q)
    if (s > 0) matches.push({ entry, score: s, i })
  })
  matches.sort((a, b) => b.score - a.score || a.entry.rank - b.entry.rank || a.i - b.i)
  const perGroup = new Map<string, number>()
  const hits: SearchHit[] = []
  for (const { entry } of matches) {
    const n = perGroup.get(entry.hit.group) ?? 0
    if (n >= PER_GROUP) continue
    perGroup.set(entry.hit.group, n + 1)
    hits.push(entry.hit)
  }
  return hits
}

export function journalHit(e: Pick<JournalEntry, 'id' | 'company' | 'header_text' | 'posting_date'>): SearchHit {
  return { id: `journal:${e.id}`, group: 'Asientos', label: e.id, hint: e.header_text, target: { kind: 'route', to: explorerRoute.journal(e.id) } }
}
