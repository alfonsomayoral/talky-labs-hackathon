// «Razonamiento por proceso»: how many items took each path of the policy, per task.
// Pure builders; ProcessMap draws them. Counts are WorkItems unless a node says otherwise (`unit`).

import type {
  ApRow,
  ArBillingRow,
  ArCashRow,
  BankRecRow,
  DatasetCore,
  Deliverables,
  DerivedRun,
  ItemId,
  RunBundle,
  TaskKey,
  WorkItem,
} from '@/domain/types'
import { CLOSE_TYPES, IC_CAUSES } from '@/domain/types'
import type { Tone } from '@/components'
import {
  AP_ACTION_CATALOG,
  AP_CASCADE,
  AP_DECISION_CATALOG,
  AP_DOCUMENT_TYPE_CATALOG,
  AP_REASON_CATALOG,
  AR_BILLING_OUTCOME_CATALOG,
  AR_RESIDUAL_CATALOG,
  BANK_CATEGORY_CATALOG,
  BANK_MATCH_ENTRY,
  CLOSE_TYPE_CATALOG,
  IC_CAUSE_CATALOG,
  type PolicyEntry,
} from '@/domain/catalog/policy'
import { effectiveDeliverables } from '@/engine'
import { BILLING_TYPE_LABELS, TASK_META } from './labels'
import { itemEurCents } from './fx'

/** What a click on a node hands to a list: the ids of the items behind it. */
export interface FlowFilter {
  id: string
  label: string
  items: ReadonlySet<ItemId>
}

export interface FlowLeaf {
  id: string
  label: string
  count: number
  /** Σ|amount| in EUR cents (other currencies at the month-end SYN-BCE rate). */
  amount: number
  section: string | null
  description: string | null
  tone: Tone
  filter: FlowFilter
}

export interface FlowNode extends FlowLeaf {
  column: number
  /** Sub-branches shown inside the node (reasons, categories…); they partition the node unless `overlapping`. */
  breakdown: FlowLeaf[]
  /** Breakdown entries may share items (e.g. a receipt with two kinds of difference). */
  overlapping?: boolean
  annotation: string | null
  /** What `count` counts when it is not items (e.g. «parejas»). Such nodes carry no links. */
  unit: string | null
}

export interface FlowLink {
  source: string
  target: string
  count: number
}

export interface ProcessFlow {
  task: TaskKey
  title: string
  /** Stage title per column (with the policy section when there is one). */
  columns: { title: string; section: string | null }[]
  nodes: FlowNode[]
  links: FlowLink[]
  total: { count: number; amount: number }
}

type FlowRun = Pick<RunBundle, 'deliverables'> & { present?: RunBundle['present'] | null }

interface Ctx {
  task: TaskKey
  core: DatasetCore
  derived: DerivedRun
  d: Deliverables
  items: WorkItem[]
}

// ---------------------------------------------------------------- building blocks
function leaf(
  ctx: Ctx,
  id: string,
  label: string,
  items: readonly WorkItem[],
  opts: { entry?: PolicyEntry | null; section?: string | null; description?: string | null; tone?: Tone } = {},
): FlowLeaf {
  const fullId = `${ctx.task}/${id}`
  return {
    id: fullId,
    label,
    count: items.length,
    amount: items.reduce((s, it) => s + Math.abs(itemEurCents(it, it.amount ?? 0, ctx.core)), 0),
    section: opts.section !== undefined ? opts.section : (opts.entry?.section ?? null),
    description: opts.description !== undefined ? opts.description : (opts.entry?.description ?? null),
    tone: opts.tone ?? 'neutral',
    filter: { id: fullId, label, items: new Set(items.map((it) => it.id)) },
  }
}

function node(
  base: FlowLeaf,
  column: number,
  extra: { breakdown?: FlowLeaf[]; annotation?: string | null; unit?: string | null; overlapping?: boolean } = {},
): FlowNode {
  return { ...base, column, breakdown: extra.breakdown ?? [], annotation: extra.annotation ?? null, unit: extra.unit ?? null, overlapping: extra.overlapping }
}

/** Groups items by a key, in first-seen order (or `order` first). */
function groupBy<K extends string>(items: readonly WorkItem[], key: (it: WorkItem) => K, order: readonly string[] = []): Map<K, WorkItem[]> {
  const m = new Map<K, WorkItem[]>()
  for (const k of order) m.set(k as K, [])
  for (const it of items) {
    const k = key(it)
    const list = m.get(k)
    if (list) list.push(it)
    else m.set(k, [it])
  }
  for (const [k, list] of m) if (!list.length) m.delete(k)
  return m
}

class FlowBuilder {
  nodes: FlowNode[] = []
  links: FlowLink[] = []
  add(n: FlowNode): FlowNode {
    this.nodes.push(n)
    return n
  }
  link(source: FlowNode, target: FlowNode, count: number) {
    if (count > 0) this.links.push({ source: source.id, target: target.id, count })
  }
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

// ---------------------------------------------------------------- AP (§2.1, §2.2 cascade)
const AP_INVOICE_DECISIONS = new Set(['DUPLICATE', 'REJECT', 'HOLD', 'POST_PAYMENT_BLOCK', 'POST'])

/** The reason that decided an item: the first of its reasons in cascade order. */
function firstCascadeReason(reasons: readonly string[], group: string): string {
  const step = AP_CASCADE.find((s) => s.group === group && reasons.includes(s.code))
  return step?.code ?? (reasons[0] || 'SIN_MOTIVO')
}

function reasonBreakdown(ctx: Ctx, items: WorkItem[], group: 'reject' | 'hold', base: string): FlowLeaf[] {
  const order = AP_CASCADE.filter((s) => s.group === group).map((s) => s.code)
  const groups = groupBy(items, (it) => firstCascadeReason(it.reasons, group), order)
  return [...groups].map(([code, list]) => {
    const entry = (AP_REASON_CATALOG as Record<string, PolicyEntry | undefined>)[code] ?? null
    return leaf(ctx, `${base}/${code}`, entry?.label ?? (code === 'SIN_MOTIVO' ? 'Sin motivo' : code), list, {
      entry,
      tone: code === 'BANK_DETAILS_CHANGED' || group === 'reject' ? 'danger' : 'warn',
    })
  })
}

function apFlow(ctx: Ctx): ProcessFlow {
  const b = new FlowBuilder()
  const rows = ctx.d.ap as ApRow[]
  const row = (it: WorkItem): ApRow | undefined => rows[it.rowIndex]
  const all = ctx.items
  const notInvoice = all.filter((i) => i.outcome === 'NOT_INVOICE')
  const unknown = all.filter((i) => i.outcome !== 'NOT_INVOICE' && !AP_INVOICE_DECISIONS.has(i.outcome))
  const invoices = all.filter((i) => AP_INVOICE_DECISIONS.has(i.outcome))
  const dup = invoices.filter((i) => i.outcome === 'DUPLICATE')
  const unique = invoices.filter((i) => i.outcome !== 'DUPLICATE')
  const reject = unique.filter((i) => i.outcome === 'REJECT')
  const valid = unique.filter((i) => i.outcome !== 'REJECT')
  const hold = valid.filter((i) => i.outcome === 'HOLD')
  const released = valid.filter((i) => i.outcome !== 'HOLD')
  const block = released.filter((i) => i.outcome === 'POST_PAYMENT_BLOCK')
  const post = released.filter((i) => i.outcome === 'POST')

  const root = b.add(node(leaf(ctx, 'received', 'Recibidos', all, { section: null, description: 'Documentos de tasks/ap_documents.json que llegaron a la bandeja en el mes.' }), 0))

  const trunk1 = b.add(
    node(
      leaf(ctx, 'invoices', 'Facturas y abonos', invoices, {
        section: '§2.1',
        description: 'Facturas, abonos y solicitudes de anticipo: pasan a la cascada de la §2.2.',
      }),
      1,
    ),
  )
  const actions = groupBy(notInvoice, (it) => String(row(it)?.action ?? 'NONE'))
  const notInvoiceNode = b.add(
    node(leaf(ctx, 'not_invoice', 'No son factura', notInvoice, { entry: AP_DECISION_CATALOG.NOT_INVOICE }), 1, {
      breakdown: [...actions].map(([action, list]) => {
        const entry = AP_ACTION_CATALOG[action as keyof typeof AP_ACTION_CATALOG] ?? null
        return leaf(ctx, `not_invoice/${action}`, entry?.label ?? action, list, { entry, tone: action === 'NONE' ? 'neutral' : 'info' })
      }),
    }),
  )
  b.link(root, trunk1, invoices.length)
  b.link(root, notInvoiceNode, notInvoice.length)
  if (unknown.length) {
    const n = b.add(
      node(leaf(ctx, 'unknown', 'Sin decisión válida', unknown, { section: '§2.2', description: 'La decisión entregada no es ninguna de las de la política.', tone: 'danger' }), 1),
    )
    b.link(root, n, unknown.length)
  }

  const trunk2 = b.add(node(leaf(ctx, 'unique', 'Sin duplicar', unique, { section: '§2.2.1', description: 'No coinciden con un documento ya recibido.' }), 2))
  const dupNode = b.add(node(leaf(ctx, 'duplicate', 'Duplicados', dup, { entry: AP_DECISION_CATALOG.DUPLICATE }), 2))
  b.link(trunk1, trunk2, unique.length)
  b.link(trunk1, dupNode, dup.length)

  const trunk3 = b.add(
    node(leaf(ctx, 'valid', 'Sin defectos', valid, { section: '§2.2.2', description: 'Cumplen los requisitos formales y fiscales de la factura.' }), 3),
  )
  const rejectNode = b.add(
    node(leaf(ctx, 'reject', 'Rechazadas', reject, { entry: AP_DECISION_CATALOG.REJECT, tone: 'danger' }), 3, {
      breakdown: reasonBreakdown(ctx, reject, 'reject', 'reject'),
    }),
  )
  b.link(trunk2, trunk3, valid.length)
  b.link(trunk2, rejectNode, reject.length)

  const trunk4 = b.add(
    node(leaf(ctx, 'released', 'Sin retención', released, { section: '§2.2.3', description: 'Proveedor dado de alta, IBAN de la ficha, mercancía recibida y precio en tolerancia.' }), 4),
  )
  const holdNode = b.add(
    node(leaf(ctx, 'hold', 'Retenidas', hold, { entry: AP_DECISION_CATALOG.HOLD, tone: 'warn' }), 4, {
      breakdown: reasonBreakdown(ctx, hold, 'hold', 'hold'),
    }),
  )
  b.link(trunk3, trunk4, released.length)
  b.link(trunk3, holdNode, hold.length)

  const payees = groupBy(
    post.filter((it) => row(it)?.payee),
    (it) => String(row(it)?.payee?.type),
  )
  const payeeNote = [...payees].map(([type, list]) => `${list.length} con pago ${type === 'FACTOR' ? 'al factor' : type === 'AEAT_EMBARGO' ? 'a la AEAT' : type}`).join(' · ')
  const postTypes = groupBy(post, (it) => String(row(it)?.document_type ?? 'INVOICE'))
  const postNode = b.add(
    node(leaf(ctx, 'post', 'Contabilizadas', post, { entry: AP_DECISION_CATALOG.POST, tone: 'ok' }), 5, {
      breakdown:
        postTypes.size > 1
          ? [...postTypes].map(([type, list]) => {
              const entry = AP_DOCUMENT_TYPE_CATALOG[type as keyof typeof AP_DOCUMENT_TYPE_CATALOG] ?? null
              return leaf(ctx, `post/${type}`, entry?.label ?? type, list, { entry, tone: 'ok' })
            })
          : [],
      annotation: payeeNote || null,
    }),
  )
  const blockNode = b.add(node(leaf(ctx, 'payment_block', 'Bloqueo de pago', block, { entry: AP_DECISION_CATALOG.POST_PAYMENT_BLOCK, tone: 'warn' }), 5))
  b.link(trunk4, postNode, post.length)
  b.link(trunk4, blockNode, block.length)

  return finish(ctx, b, [
    { title: 'Entrada', section: null },
    { title: 'Tipo de documento', section: '§2.1' },
    { title: 'Duplicados', section: '§2.2.1' },
    { title: 'Requisitos', section: '§2.2.2' },
    { title: 'Retención', section: '§2.2.3' },
    { title: 'Pago', section: '§2.2.4' },
  ])
}

// ---------------------------------------------------------------- AR billing (§3.1)
function arBillingFlow(ctx: Ctx): ProcessFlow {
  const b = new FlowBuilder()
  const rows = ctx.d.ar_billing as ArBillingRow[]
  const row = (it: WorkItem) => rows[it.rowIndex]
  const all = ctx.items
  const invoice = all.filter((i) => i.outcome === 'INVOICE')
  const skip = all.filter((i) => i.outcome === 'SKIP_PENDING_APPROVAL')
  const other = all.filter((i) => i.outcome !== 'INVOICE' && i.outcome !== 'SKIP_PENDING_APPROVAL')

  const root = b.add(node(leaf(ctx, 'items', 'Partidas', all, { description: 'Partidas de tasks/ar_billing_items.json: certificaciones, servicios, revisiones y energía.' }), 0))
  const face = invoice.filter((it) => {
    const f = row(it)?.invoice?.face
    return !!f && typeof f === 'object'
  }).length
  const invoiceNode = b.add(
    node(leaf(ctx, 'invoice', 'Facturar', invoice, { entry: AR_BILLING_OUTCOME_CATALOG.INVOICE, tone: 'ok' }), 1, {
      annotation: face ? `${plural(face, 'factura', 'facturas')} por FACe con DIR3` : null,
    }),
  )
  const skipNode = b.add(
    node(leaf(ctx, 'skip', 'Pendiente de aprobación', skip, { entry: AR_BILLING_OUTCOME_CATALOG.SKIP_PENDING_APPROVAL, tone: 'warn' }), 1, {
      annotation: skip.length ? 'Se registra como obra pendiente en Cierre (§5)' : null,
    }),
  )
  b.link(root, invoiceNode, invoice.length)
  b.link(root, skipNode, skip.length)
  if (other.length) {
    const n = b.add(node(leaf(ctx, 'unknown', 'Sin decisión válida', other, { section: '§3.1', description: 'El valor de expected no es INVOICE ni SKIP_PENDING_APPROVAL.', tone: 'danger' }), 1))
    b.link(root, n, other.length)
  }
  const typeOf = (it: WorkItem) => {
    const r = row(it) as Record<string, unknown> | undefined
    return typeof r?.type === 'string' ? r.type : 'OTRO'
  }
  for (const [type, list] of groupBy(invoice, typeOf, Object.keys(BILLING_TYPE_LABELS))) {
    const n = b.add(node(leaf(ctx, `type/${type}`, BILLING_TYPE_LABELS[type] ?? 'Otro tipo', list, { section: '§3.1', description: null, tone: 'ok' }), 2))
    b.link(invoiceNode, n, list.length)
  }
  return finish(ctx, b, [
    { title: 'Entrada', section: null },
    { title: 'Decisión', section: '§3.1' },
    { title: 'Tipo de contrato', section: '§3.1' },
  ])
}

// ---------------------------------------------------------------- AR cash (§3.2)
type Application = 'single' | 'grouped' | 'pagare' | 'partial' | 'none'
const APPLICATION_LABELS: Record<Application, { label: string; description: string; tone: Tone }> = {
  single: { label: 'Aplicación exacta', description: 'El abono paga una sola factura por su importe.', tone: 'ok' },
  grouped: { label: 'Pago agrupado', description: 'Un abono sin referencia que paga varias facturas del cliente.', tone: 'ok' },
  pagare: { label: 'Pagaré', description: 'Pagaré al vencimiento aplicado a 43100000 (asignación PAG<número>).', tone: 'ok' },
  partial: { label: 'Aplicación parcial', description: 'El cliente paga de menos sin causa conocida: el resto queda abierto.', tone: 'warn' },
  none: { label: 'Sin aplicación', description: 'El abono no se aplica a facturas: se explica con una diferencia o no es de un cliente.', tone: 'neutral' },
}

function arCashFlow(ctx: Ctx): ProcessFlow {
  const b = new FlowBuilder()
  const rows = ctx.d.ar_cash as ArCashRow[]
  const row = (it: WorkItem) => rows[it.rowIndex]
  const all = ctx.items
  const apps = (it: WorkItem) => (Array.isArray(row(it)?.applications) ? row(it).applications : [])
  const application = (it: WorkItem): Application => {
    const a = apps(it)
    if (!a.length) return 'none'
    if (a.some((x) => x.pagare)) return 'pagare'
    if (it.outcome === 'PARTIAL') return 'partial'
    return a.length > 1 ? 'grouped' : 'single'
  }
  const customer = all.filter((it) => row(it)?.customer != null)
  const nonCustomer = all.filter((it) => row(it)?.customer == null)

  const root = b.add(node(leaf(ctx, 'receipts', 'Abonos', all, { description: 'Líneas de abono de tasks/ar_receipts.json, ya registradas contra 55500000.' }), 0))
  const custNode = b.add(node(leaf(ctx, 'customer', 'Cliente identificado', customer, { section: '§3.2', description: 'El abono viene de un cliente del maestro.' }), 1))
  const nonNode = b.add(node(leaf(ctx, 'non_customer', 'No es cliente', nonCustomer, { entry: AR_RESIDUAL_CATALOG.NON_CUSTOMER, tone: 'warn' }), 1))
  b.link(root, custNode, customer.length)
  b.link(root, nonNode, nonCustomer.length)

  const order: Application[] = ['single', 'grouped', 'pagare', 'partial', 'none']
  const appNodes = new Map<Application, FlowNode>()
  for (const key of order) {
    const list = all.filter((it) => application(it) === key)
    if (!list.length) continue
    const meta = APPLICATION_LABELS[key]
    const n = b.add(node(leaf(ctx, `application/${key}`, meta.label, list, { section: '§3.2', description: meta.description, tone: meta.tone }), 2))
    appNodes.set(key, n)
    b.link(custNode, n, list.filter((it) => row(it)?.customer != null).length)
    b.link(nonNode, n, list.filter((it) => row(it)?.customer == null).length)
  }

  const residualTypes = (it: WorkItem) => it.reasons
  const clean = all.filter((it) => !residualTypes(it).length)
  const withDiff = all.filter((it) => residualTypes(it).length > 0)
  const cleanNode = b.add(node(leaf(ctx, 'no_difference', 'Sin diferencias', clean, { section: '§3.2', description: 'El abono se aplica entero: el ajuste solo vacía 55500000.', tone: 'ok' }), 3))
  const types = new Map<string, WorkItem[]>()
  for (const it of withDiff) for (const t of new Set(residualTypes(it))) types.set(t, [...(types.get(t) ?? []), it])
  const diffNode = b.add(
    node(leaf(ctx, 'difference', 'Con diferencias', withDiff, { section: '§3.2', description: 'Parte del abono se explica con una causa conocida.', tone: 'warn' }), 3, {
      breakdown: [...types].map(([type, list]) => {
        const entry = AR_RESIDUAL_CATALOG[type as keyof typeof AR_RESIDUAL_CATALOG] ?? null
        return leaf(ctx, `difference/${type}`, entry?.label ?? type, list, { entry, tone: entry?.attention ? 'warn' : 'neutral' })
      }),
      overlapping: withDiff.some((it) => new Set(residualTypes(it)).size > 1),
    }),
  )
  for (const [key, n] of appNodes) {
    const list = all.filter((it) => application(it) === key)
    b.link(n, cleanNode, list.filter((it) => !residualTypes(it).length).length)
    b.link(n, diffNode, list.filter((it) => residualTypes(it).length > 0).length)
  }
  return finish(ctx, b, [
    { title: 'Entrada', section: null },
    { title: 'Cliente', section: '§3.2' },
    { title: 'Aplicación', section: '§3.2' },
    { title: 'Diferencias', section: '§3.2' },
  ])
}

// ---------------------------------------------------------------- bank reconciliation (§4)
type BankSide = 'match' | 'bank' | 'book' | 'orphan'

function bankSide(it: WorkItem): BankSide {
  const bank = it.evidence.some((e) => e.kind === 'bank')
  const book = it.evidence.some((e) => e.kind === 'journal')
  if (bank && book) return 'match'
  if (bank) return 'bank'
  if (book) return 'book'
  return 'orphan'
}

function matchShape(it: WorkItem): string {
  const banks = it.evidence.filter((e) => e.kind === 'bank').length
  const books = it.evidence.filter((e) => e.kind === 'journal').length
  if (banks === 1 && books === 1) return '1:1'
  if (books === 1) return 'N:1'
  if (banks === 1) return '1:N'
  return 'N:M'
}

const MATCH_SHAPES: Record<string, string> = {
  '1:1': 'Una línea con un apunte.',
  'N:1': 'Varias líneas del extracto contra un apunte (p. ej. una nómina en dos lotes).',
  '1:N': 'Una línea del extracto contra varios apuntes (p. ej. una remesa de pagos).',
  'N:M': 'Varias líneas contra varios apuntes.',
}

const bankEntry = (category: string): PolicyEntry | null =>
  category === 'MATCH' ? BANK_MATCH_ENTRY : (BANK_CATEGORY_CATALOG[category as keyof typeof BANK_CATEGORY_CATALOG] ?? null)

function categoryBreakdown(ctx: Ctx, items: WorkItem[], base: string, tone: Tone): FlowLeaf[] {
  return [...groupBy(items, (it) => it.outcome)].map(([category, list]) => {
    const entry = bankEntry(category)
    return leaf(ctx, `${base}/${category}`, entry?.label ?? category, list, { entry, tone })
  })
}

function bankFlow(ctx: Ctx): ProcessFlow {
  const b = new FlowBuilder()
  const rows = ctx.d.bank_rec as BankRecRow[]
  const all = ctx.items
  const adjusted = (it: WorkItem): boolean => {
    const r = rows[it.rowIndex]
    const cats = new Set((Array.isArray(r?.adjustments) ? r.adjustments : []).map((a) => String(a.category)))
    return cats.has(it.outcome)
  }
  const bySide = (side: BankSide) => all.filter((it) => bankSide(it) === side)
  const matched = bySide('match')
  const unBank = bySide('bank')
  const unBook = bySide('book')
  const orphan = bySide('orphan')

  let bankLines = 0
  let bookLines = 0
  for (const r of rows) {
    for (const m of Array.isArray(r.matches) ? r.matches : []) {
      bankLines += Array.isArray(m.bank_lines) ? m.bank_lines.length : 0
      bookLines += Array.isArray(m.book_lines) ? m.book_lines.length : 0
    }
    bankLines += Array.isArray(r.unmatched_bank) ? r.unmatched_bank.length : 0
    bookLines += Array.isArray(r.unmatched_book) ? r.unmatched_book.length : 0
  }

  const root = b.add(
    node(leaf(ctx, 'items', 'Partidas', all, { section: '§4', description: 'Casaciones y líneas sin casar de las cuentas de tasks/bank_accounts.json.' }), 0, {
      annotation: `${plural(bankLines, 'línea', 'líneas')} del extracto · ${plural(bookLines, 'apunte', 'apuntes')} del libro · ${plural(rows.length, 'cuenta', 'cuentas')}`,
    }),
  )
  const shapes = groupBy(matched, matchShape, ['1:1', 'N:1', '1:N', 'N:M'])
  const matchNode = b.add(
    node(leaf(ctx, 'matched', 'Casadas', matched, { entry: BANK_MATCH_ENTRY, tone: 'ok' }), 1, {
      breakdown: [...shapes].map(([shape, list]) => leaf(ctx, `matched/${shape.replace(':', 'x')}`, `Casación ${shape}`, list, { section: '§4', description: MATCH_SHAPES[shape], tone: 'ok' })),
    }),
  )
  const bankNode = b.add(
    node(leaf(ctx, 'unmatched_bank', 'Sin casar en el extracto', unBank, { section: '§4', description: 'Movimientos del banco sin apunte en la cuenta 572.', tone: 'warn' }), 1, {
      breakdown: categoryBreakdown(ctx, unBank, 'unmatched_bank', 'warn'),
    }),
  )
  const bookNode = b.add(
    node(leaf(ctx, 'unmatched_book', 'Sin casar en libros', unBook, { section: '§4', description: 'Apuntes de la cuenta 572 sin movimiento en el extracto del mes.', tone: 'warn' }), 1, {
      breakdown: categoryBreakdown(ctx, unBook, 'unmatched_book', 'warn'),
    }),
  )
  b.link(root, matchNode, matched.length)
  b.link(root, bankNode, unBank.length)
  b.link(root, bookNode, unBook.length)
  const col1: FlowNode[] = [matchNode, bankNode, bookNode]
  if (orphan.length) {
    const n = b.add(node(leaf(ctx, 'orphan', 'Ajustes sin partida', orphan, { section: '§4', description: 'Ajustes entregados cuya categoría no tiene ninguna línea sin casar.', tone: 'warn' }), 1))
    b.link(root, n, orphan.length)
    col1.push(n)
  }

  const plain = all.filter((it) => it.outcome === 'MATCH')
  const withAdj = all.filter((it) => it.outcome !== 'MATCH' && adjusted(it))
  const noAdj = all.filter((it) => it.outcome !== 'MATCH' && !adjusted(it))
  const cleanNode = b.add(node(leaf(ctx, 'clean', 'Cuadran sin ajuste', plain, { section: '§4', description: 'Casadas por el mismo importe: no hace falta asiento.', tone: 'ok' }), 2))
  const adjNode = b.add(
    node(leaf(ctx, 'adjusted', 'Con asiento de ajuste', withAdj, { section: '§4', description: 'La diferencia se corrige con un asiento contra la cuenta 572.', tone: 'info' }), 2, {
      breakdown: categoryBreakdown(ctx, withAdj, 'adjusted', 'info'),
    }),
  )
  const openNode = b.add(
    node(
      leaf(ctx, 'not_adjusted', 'Sin ajuste', noAdj, {
        section: '§4',
        description: 'Se explican sin asiento: pagos pendientes, traspasos en tránsito, partidas del mes anterior o errores del banco.',
        tone: 'neutral',
      }),
      2,
      { breakdown: categoryBreakdown(ctx, noAdj, 'not_adjusted', 'neutral') },
    ),
  )
  const group = (n: FlowNode) => all.filter((it) => n.filter.items.has(it.id))
  for (const n of col1) {
    const list = group(n)
    b.link(n, cleanNode, list.filter((it) => it.outcome === 'MATCH').length)
    b.link(n, adjNode, list.filter((it) => it.outcome !== 'MATCH' && adjusted(it)).length)
    b.link(n, openNode, list.filter((it) => it.outcome !== 'MATCH' && !adjusted(it)).length)
  }
  return finish(ctx, b, [
    { title: 'Entrada', section: null },
    { title: 'Casación', section: '§4' },
    { title: 'Ajuste', section: '§4' },
  ])
}

// ---------------------------------------------------------------- intercompany (§6)
const pairOf = (it: WorkItem) => it.key.split('/')[0]

function icFlow(ctx: Ctx): ProcessFlow {
  const b = new FlowBuilder()
  const all = ctx.items
  const pairs = (ctx.core.tasks?.intercompany?.pairs ?? []).map((p) => [...p].map(String).sort().join('-'))
  const withDiff = new Set(all.map(pairOf))
  const cleanPairs = pairs.filter((p) => !withDiff.has(p))

  const root = b.add(
    node(leaf(ctx, 'differences', 'Diferencias', all, { section: '§6', description: 'Diferencias entre saldos recíprocos de las parejas de tasks/intercompany.json.' }), 0, {
      annotation: pairs.length ? `En ${withDiff.size} de ${plural(pairs.length, 'pareja', 'parejas')}` : null,
    }),
  )
  if (pairs.length) {
    b.add(
      node(
        { ...leaf(ctx, 'clean_pairs', 'Parejas que cuadran', [], { section: '§6', description: 'Parejas revisadas sin diferencias.', tone: 'ok' }), count: cleanPairs.length },
        0,
        { unit: cleanPairs.length === 1 ? 'pareja' : 'parejas', annotation: cleanPairs.map((p) => p.replace('-', '–')).join(' · ') || null },
      ),
    )
  }
  const causes = groupBy(all, (it) => it.outcome, IC_CAUSES)
  const causeNodes: FlowNode[] = []
  for (const [cause, list] of causes) {
    const entry = IC_CAUSE_CATALOG[cause as keyof typeof IC_CAUSE_CATALOG] ?? null
    const n = b.add(
      node(leaf(ctx, `cause/${cause}`, entry?.label ?? cause, list, { entry, section: entry?.section ?? '§6', tone: 'warn' }), 1, {
        annotation: [...new Set(list.map(pairOf))].map((p) => p.replace('-', '–')).join(' · '),
      }),
    )
    causeNodes.push(n)
    b.link(root, n, list.length)
  }
  const adjusted = all.filter((it) => it.status !== 'OPEN')
  const open = all.filter((it) => it.status === 'OPEN')
  const responsible = groupBy(adjusted, (it) => String(it.company ?? '—'))
  const adjNode = b.add(
    node(leaf(ctx, 'adjusted', 'Con asiento corrector', adjusted, { section: '§6', description: 'La sociedad responsable registra el asiento que iguala los saldos.', tone: 'info' }), 2, {
      breakdown: [...responsible].map(([company, list]) => leaf(ctx, `adjusted/${company}`, `Corrige ${company}`, list, { section: '§6', description: null, tone: 'info' })),
    }),
  )
  const openNode = b.add(
    node(
      leaf(ctx, 'not_adjusted', 'Sin ajuste', open, {
        section: '§6',
        description: 'Se corrige en otra tarea (p. ej. el barrido de pooling en la conciliación bancaria).',
        tone: 'neutral',
      }),
      2,
    ),
  )
  for (const n of causeNodes) {
    const list = all.filter((it) => n.filter.items.has(it.id))
    b.link(n, adjNode, list.filter((it) => it.status !== 'OPEN').length)
    b.link(n, openNode, list.filter((it) => it.status === 'OPEN').length)
  }
  return finish(ctx, b, [
    { title: 'Entrada', section: null },
    { title: 'Causa', section: '§6' },
    { title: 'Ajuste', section: '§6' },
  ])
}

// ---------------------------------------------------------------- close (§5)
function closeFlow(ctx: Ctx): ProcessFlow {
  const b = new FlowBuilder()
  const all = ctx.items
  const steps = ctx.core.tasks?.close?.steps?.length ? ctx.core.tasks.close.steps : [...CLOSE_TYPES]
  const root = b.add(node(leaf(ctx, 'items', 'Partidas de cierre', all, { section: '§5', description: 'Asientos de fin de mes de tasks/close.json (sus retrocesiones del día 1 no se entregan).' }), 0))
  const attention = new Set(ctx.derived.attention.map((a) => a.item))
  const companyName = (code: string) => ctx.core.companies?.find((c) => c.code === code)?.short ?? code
  const typeNodes: FlowNode[] = []
  for (const [type, list] of groupBy(all, (it) => it.outcome, steps)) {
    const entry = CLOSE_TYPE_CATALOG[type as keyof typeof CLOSE_TYPE_CATALOG] ?? null
    const companies = groupBy(list, (it) => String(it.company ?? '—'))
    const n = b.add(
      node(leaf(ctx, `type/${type}`, entry?.label ?? type, list, { entry, section: entry?.section ?? '§5', tone: 'neutral' }), 1, {
        breakdown:
          companies.size > 1 ? [...companies].map(([company, l]) => leaf(ctx, `type/${type}/${company}`, `${company} · ${companyName(company)}`, l, { section: null, description: null })) : [],
      }),
    )
    typeNodes.push(n)
    b.link(root, n, list.length)
  }
  for (const type of steps) {
    if (all.some((it) => it.outcome === type)) continue
    const entry = CLOSE_TYPE_CATALOG[type as keyof typeof CLOSE_TYPE_CATALOG] ?? null
    b.add(node(leaf(ctx, `type/${type}`, entry?.label ?? type, [], { entry, section: entry?.section ?? '§5' }), 1))
  }
  const review = all.filter((it) => attention.has(it.id))
  const done = all.filter((it) => !attention.has(it.id))
  const doneNode = b.add(node(leaf(ctx, 'resolved', 'Sin revisión', done, { section: '§5', description: 'Calculadas con la regla de la política sin señales que pidan revisión.', tone: 'ok' }), 2))
  const reviewNode = b.add(
    node(
      leaf(ctx, 'review', 'A revisar', review, {
        section: '§5',
        description: 'Estimaciones por encima de 50.000 € u otras señales que pasan a Atención.',
        tone: 'warn',
      }),
      2,
    ),
  )
  for (const n of typeNodes) {
    const list = all.filter((it) => n.filter.items.has(it.id))
    b.link(n, doneNode, list.filter((it) => !attention.has(it.id)).length)
    b.link(n, reviewNode, list.filter((it) => attention.has(it.id)).length)
  }
  return finish(ctx, b, [
    { title: 'Entrada', section: null },
    { title: 'Tipo de partida', section: '§5' },
    { title: 'Revisión', section: null },
  ])
}

// ---------------------------------------------------------------- entry point
function finish(ctx: Ctx, b: FlowBuilder, columns: ProcessFlow['columns']): ProcessFlow {
  const root = b.nodes[0]
  return {
    task: ctx.task,
    title: TASK_META[ctx.task].title,
    columns,
    nodes: b.nodes,
    links: b.links,
    total: { count: root?.count ?? 0, amount: root?.amount ?? 0 },
  }
}

const BUILDERS: Record<TaskKey, (ctx: Ctx) => ProcessFlow> = {
  ap: apFlow,
  ar_billing: arBillingFlow,
  ar_cash: arCashFlow,
  bank_rec: bankFlow,
  ic: icFlow,
  close: closeFlow,
}

/** Decision map of a task: nodes per policy stage with counts, EUR amounts and the item ids behind each branch. */
export function processFlow(task: TaskKey, derived: DerivedRun, core: DatasetCore, run: FlowRun): ProcessFlow {
  const ctx: Ctx = { task, core, derived, d: effectiveDeliverables(run), items: derived.items.filter((it) => it.task === task) }
  return BUILDERS[task](ctx)
}

/** Node or breakdown entry by id (e.g. to restore a filter from the URL). */
export function findFlowFilter(flow: ProcessFlow | null, id: string | null | undefined): FlowFilter | null {
  if (!flow || !id) return null
  for (const n of flow.nodes) {
    if (n.id === id) return n.filter
    const sub = n.breakdown.find((x) => x.id === id)
    if (sub) return sub.filter
  }
  return null
}

/**
 * Conservation problems of a flow (empty when sound): links in = node count for non-root nodes,
 * links out = node count for nodes that branch, breakdowns partition their node.
 */
export function flowIssues(flow: ProcessFlow): string[] {
  const issues: string[] = []
  const sum = (xs: FlowLink[]) => xs.reduce((s, l) => s + l.count, 0)
  for (const n of flow.nodes) {
    if (n.unit) continue
    const incoming = flow.links.filter((l) => l.target === n.id)
    const outgoing = flow.links.filter((l) => l.source === n.id)
    if (n.column > 0 && n.count > 0 && sum(incoming) !== n.count) issues.push(`${n.id}: entra ${sum(incoming)} ≠ ${n.count}`)
    if (outgoing.length && sum(outgoing) !== n.count) issues.push(`${n.id}: sale ${sum(outgoing)} ≠ ${n.count}`)
    if (n.breakdown.length && !n.overlapping) {
      const parts = n.breakdown.reduce((s, x) => s + x.count, 0)
      if (parts !== n.count) issues.push(`${n.id}: desglose ${parts} ≠ ${n.count}`)
    }
    for (const x of n.breakdown) for (const id of x.filter.items) if (!n.filter.items.has(id)) issues.push(`${x.id}: ${id} fuera del nodo`)
  }
  return issues
}
