// Pure builders behind ReasoningView: the AP cascade, the ordered steps of a trace, and a
// task-specific summary («por qué») built from the delivered row and the dataset.

import type {
  AgentEvent,
  ApRow,
  ArBillingRow,
  ArCashRow,
  BankLine,
  BankRecRow,
  DatasetCore,
  EventKind,
  EventResult,
  EvidenceRef,
  IcRow,
  JournalEntryOut,
  ModelCall,
  WorkItem,
} from '@/domain/types'
import type { Tone } from '@/components'
import {
  AP_ACTION_CATALOG,
  AP_CASCADE,
  AP_DOCUMENT_TYPE_CATALOG,
  AP_PAYEE_CATALOG,
  AP_REASON_CATALOG,
  AR_RESIDUAL_CATALOG,
  BANK_CATEGORY_CATALOG,
  CLOSE_TYPE_CATALOG,
  IC_CAUSE_CATALOG,
  accountLabel,
  type CascadeGroup,
  type CascadeStep,
} from '@/domain/catalog/policy'
import { formatDate, formatMoney, formatNumber, formatPercent } from '@/lib/format'
import { BILLING_TYPE_LABELS } from './labels'

// ---------------------------------------------------------------- AP cascade (§2.2)
export type CheckState = 'pass' | 'fail' | 'skipped'

export interface CascadeCheck {
  step: CascadeStep
  state: CheckState
  /** What failed (reason label, duplicate id…) or the event summary. */
  detail: string | null
  /** Taken from a real agent event (vs reconstructed from the decision). */
  fromEvent: boolean
}

const DECISION_GROUP: Record<string, CascadeGroup> = {
  DUPLICATE: 'duplicate',
  REJECT: 'reject',
  HOLD: 'hold',
  POST_PAYMENT_BLOCK: 'payment_block',
  POST: 'post',
}

const CASCADE_STEP_IDS = new Set<string>([...AP_CASCADE.map((s) => s.step), 'reject', 'hold', 'payment_block'])

const reasonLabel = (code: string) => AP_REASON_CATALOG[code as keyof typeof AP_REASON_CATALOG]?.label ?? code

/** §2.2 checks in order: ✓ until the one that decides, ✗ there, the rest not evaluated. Null when not an invoice. */
export function apCascade(row: Partial<ApRow> | null | undefined, events: readonly AgentEvent[] = []): CascadeCheck[] | null {
  const group = row ? DECISION_GROUP[String(row.decision)] : undefined
  const checkEvents = events.filter((e) => e.kind === 'CHECK' && CASCADE_STEP_IDS.has(e.step))
  if (!group && !checkEvents.length) return null
  const reasons = [
    ...(Array.isArray(row?.reasons) ? row.reasons.map(String) : []),
    ...(row?.payment_block ? [String(row.payment_block)] : []),
    ...(row?.decision === 'DUPLICATE' ? ['DUPLICATE'] : []),
  ]
  let failIdx = -1
  if (group && group !== 'post') {
    failIdx = AP_CASCADE.findIndex((s) => s.group === group && reasons.includes(s.code))
    if (failIdx < 0) failIdx = AP_CASCADE.findIndex((s) => s.group === group)
  }
  const checks: CascadeCheck[] = AP_CASCADE.map((step, i) => {
    if (failIdx < 0) return { step, state: 'pass', detail: null, fromEvent: false }
    if (i < failIdx) return { step, state: 'pass', detail: null, fromEvent: false }
    if (i > failIdx) return { step, state: 'skipped', detail: null, fromEvent: false }
    const own = reasons.find((r) => r === step.code)
    const detail =
      step.code === 'DUPLICATE'
        ? `Duplicado de ${String(row?.duplicate_of ?? '¿?')}`
        : own
          ? reasonLabel(own)
          : reasons.length
            ? reasons.map(reasonLabel).join(', ')
            : 'sin motivo informado'
    return { step, state: 'fail', detail, fromEvent: false }
  })
  for (const e of checkEvents) {
    const idx = AP_CASCADE.findIndex((s) => s.step === e.step)
    if (idx < 0) continue
    checks[idx] = { step: checks[idx].step, state: e.result === 'FAIL' ? 'fail' : 'pass', detail: e.summary || null, fromEvent: true }
  }
  return checks
}

// ---------------------------------------------------------------- steps of a trace
export interface ReasoningStep {
  key: string
  kind: EventKind | 'CASCADE'
  result: EventResult
  title: string
  policyRef: string | null
  evidence: EvidenceRef[]
  model: ModelCall | null
  confidence: number | null
  durationMs: number | null
  ts: string | null
  /** Only for kind CASCADE. */
  cascade?: CascadeCheck[]
}

export function cascadeTitle(checks: readonly CascadeCheck[]): string {
  const fail = checks.findIndex((c) => c.state === 'fail')
  const total = checks.length - 1
  if (fail < 0) return `Cascada §2.2: supera las ${total} comprobaciones`
  const c = checks[fail]
  return `Cascada §2.2: se detiene en «${c.step.label}» (${fail + 1} de ${total})`
}

const eventStep = (e: AgentEvent): ReasoningStep => ({
  key: e.event_id,
  kind: e.kind,
  result: e.result,
  title: e.summary,
  policyRef: e.policy_ref ?? null,
  evidence: e.evidence ?? [],
  model: e.model ?? null,
  confidence: typeof e.confidence === 'number' ? e.confidence : null,
  durationMs: typeof e.duration_ms === 'number' ? e.duration_ms : null,
  ts: e.ts ?? null,
})

/**
 * Ordered steps of an item: one per event, with the consecutive §2.2 CHECK events folded into a
 * single CASCADE step. When `cascade` is given and no event covers it, it goes before the decision.
 */
export function reasoningSteps(events: readonly AgentEvent[], cascade: CascadeCheck[] | null = null): ReasoningStep[] {
  const sorted = [...events].sort((a, b) => a.seq - b.seq)
  const out: ReasoningStep[] = []
  let folded = false
  for (const e of sorted) {
    const isCascade = e.kind === 'CHECK' && CASCADE_STEP_IDS.has(e.step)
    if (isCascade && cascade) {
      if (!folded) {
        folded = true
        out.push(cascadeStep(cascade, e))
      } else {
        const step = out.find((s) => s.kind === 'CASCADE')!
        step.evidence = [...step.evidence, ...(e.evidence ?? [])]
        if (step.durationMs !== null && typeof e.duration_ms === 'number') step.durationMs += e.duration_ms
      }
      continue
    }
    out.push(eventStep(e))
  }
  if (cascade && !folded) {
    const at = out.findIndex((s) => s.kind === 'DECIDE')
    out.splice(at < 0 ? out.length : at, 0, cascadeStep(cascade, null))
  }
  return out
}

function cascadeStep(checks: CascadeCheck[], first: AgentEvent | null): ReasoningStep {
  return {
    key: `cascade-${first?.event_id ?? 'row'}`,
    kind: 'CASCADE',
    result: checks.some((c) => c.state === 'fail') ? 'FAIL' : 'PASS',
    title: cascadeTitle(checks),
    policyRef: '§2.2',
    evidence: first?.evidence ?? [],
    model: null,
    confidence: null,
    durationMs: typeof first?.duration_ms === 'number' ? first.duration_ms : null,
    ts: first?.ts ?? null,
    cascade: checks,
  }
}

// ---------------------------------------------------------------- task summary
export interface ReasoningFact {
  label: string
  text?: string
  mono?: string
  cents?: number
  currency?: string
  tone?: Tone
}

export interface ReasoningSummary {
  /** One sentence: what was decided and why. */
  headline: string
  facts: ReasoningFact[]
}

export interface SummaryInput {
  item: WorkItem
  /** Deliverable rows behind the item (bank: the account row; close: every row of the group). */
  rows: readonly unknown[]
  core: DatasetCore
  entries: readonly JournalEntryOut[]
}

const money = (cents: unknown, currency: string | null | undefined) => formatMoney(typeof cents === 'number' ? cents : null, currency ?? 'EUR')
const lines = (n: number, one: string, many: string) => `${formatNumber(n)} ${n === 1 ? one : many}`
const str = (x: unknown): string | null => (typeof x === 'string' && x ? x : null)
const num = (x: unknown): number | null => (typeof x === 'number' && Number.isFinite(x) ? x : null)
const lineCount = (entries: readonly JournalEntryOut[]) => entries.reduce((s, e) => s + e.lines.length, 0)

function apSummary({ item, rows, core, entries }: SummaryInput): ReasoningSummary {
  const row = (rows[0] ?? {}) as Partial<ApRow>
  const cur = str(row.currency) ?? item.currency ?? 'EUR'
  const vendor = row.vendor_id ? core.vendors?.find((v) => v.id === row.vendor_id) : undefined
  const docType = AP_DOCUMENT_TYPE_CATALOG[row.document_type as keyof typeof AP_DOCUMENT_TYPE_CATALOG]?.label ?? String(row.document_type ?? 'Documento')
  const inbox = core.apInbox?.find((d) => d.docId === item.key)
  const checks = apCascade(row)
  const fail = checks?.findIndex((c) => c.state === 'fail') ?? -1
  const posted = lineCount(entries)
  const payee = row.payee?.type ? AP_PAYEE_CATALOG[row.payee.type as keyof typeof AP_PAYEE_CATALOG] : null
  let headline: string
  switch (row.decision) {
    case 'POST':
      headline = `Supera las ${AP_CASCADE.length - 1} comprobaciones de la §2.2 y se contabiliza${posted ? ` con un asiento de ${lines(posted, 'línea', 'líneas')}` : ''}.${payee ? ` ${payee.label}.` : ''}`
      break
    case 'POST_PAYMENT_BLOCK':
      headline = `Se contabiliza con el pago bloqueado: el subcontratista no tiene certificado del art. 43 vigente (§2.2.4).`
      break
    case 'DUPLICATE':
      headline = `Duplicado de ${String(row.duplicate_of ?? '¿?')}: mismo proveedor, número e importe que un documento ya recibido (§2.2.1).`
      break
    case 'NOT_INVOICE': {
      const action = row.action ? AP_ACTION_CATALOG[row.action as keyof typeof AP_ACTION_CATALOG] : null
      headline = `No es una factura (${docType}): ${action && row.action !== 'NONE' ? `${action.label.toLowerCase()}.` : 'no se contabiliza ni requiere acción.'}`
      break
    }
    case 'REJECT':
    case 'HOLD': {
      const c = fail >= 0 && checks ? checks[fail] : null
      const verb = row.decision === 'REJECT' ? 'Rechazada' : 'Retenida'
      headline = c
        ? `${verb} en la comprobación ${fail + 1} de ${AP_CASCADE.length - 1}: ${c.detail ?? c.step.label} (${c.step.section}).`
        : `${verb} por la §2.2.`
      break
    }
    default:
      headline = `Decisión entregada: ${String(row.decision ?? item.outcome)}.`
  }
  const facts: ReasoningFact[] = [{ label: 'Documento', text: docType }]
  facts.push(
    vendor
      ? { label: 'Proveedor', mono: vendor.id, text: vendor.name }
      : { label: 'Proveedor', text: row.vendor_id ? `${row.vendor_id} (no está en el maestro)` : 'Sin alta en el maestro', tone: 'warn' },
  )
  if (row.invoice_number || row.invoice_date) facts.push({ label: 'Factura', mono: str(row.invoice_number) ?? '—', text: row.invoice_date ? `del ${formatDate(row.invoice_date)}` : undefined })
  if (inbox) facts.push({ label: 'Recibido', text: `${inbox.message.channel} · ${formatDate(inbox.message.received_at?.slice(0, 10))}` })
  if (num(row.gross) !== null) {
    const parts = [`base ${money(row.net, cur)}`, `IVA ${money(row.tax, cur)}`]
    if (num(row.withholding)) parts.push(`retención ${money(row.withholding, cur)}`)
    if (num(row.retention)) parts.push(`garantía ${money(row.retention, cur)}`)
    facts.push({ label: 'Importes', text: parts.join(' · ') })
    facts.push({ label: 'A pagar', cents: num(row.payable) ?? num(row.gross) ?? undefined, currency: cur })
  }
  const rowLines = Array.isArray(row.lines) ? row.lines : []
  if (rowLines.length) {
    const pos = [...new Set(rowLines.map((l) => str(l.po)).filter((x): x is string => !!x))]
    facts.push({ label: 'Imputación', text: `${lines(rowLines.length, 'línea', 'líneas')}${pos.length ? ` · ${pos.length === 1 ? 'pedido' : 'pedidos'} ${pos.join(', ')}` : ' sin pedido'}` })
  }
  if (payee) facts.push({ label: 'Beneficiario', text: payee.description, tone: 'info' })
  if (row.payment_block) facts.push({ label: 'Bloqueo de pago', text: 'Certificado art. 43 caducado', tone: 'warn' })
  return { headline, facts }
}

function arBillingSummary({ item, rows, core }: SummaryInput): ReasoningSummary {
  const row = (rows[0] ?? {}) as Partial<ArBillingRow> & Record<string, unknown>
  const inv = row.invoice ?? null
  const cur = str(inv?.currency) ?? item.currency ?? 'EUR'
  const type = BILLING_TYPE_LABELS[String(row.type)] ?? 'Partida'
  const customer = str(row.customer) ? core.customers?.find((c) => c.id === row.customer) : undefined
  const who = customer?.name ?? str(row.customer) ?? item.counterparty ?? 'el cliente'
  const headline =
    row.expected === 'SKIP_PENDING_APPROVAL'
      ? `No se factura: la certificación de ${who} está pendiente de aprobación por la Dirección Facultativa; el cierre registra la obra pendiente (§3.1, §5).`
      : inv
        ? `${type} del contrato ${String(row.contract ?? '—')} a ${who}: base ${money(inv.net, cur)} + IVA ${money(inv.tax, cur)}, a cobrar ${money(inv.payable, cur)}.`
        : `${type}: ${String(row.expected ?? item.outcome)}.`
  const facts: ReasoningFact[] = [{ label: 'Tipo', text: type }]
  if (row.contract) facts.push({ label: 'Contrato', mono: String(row.contract) })
  facts.push({ label: 'Cliente', mono: str(row.customer) ?? undefined, text: customer?.name ?? undefined })
  if (inv) {
    facts.push({ label: 'Fecha', text: `${formatDate(inv.date)} · vence ${formatDate(inv.due_date)}` })
    facts.push({ label: 'IVA', mono: String(inv.tax_code ?? '—'), text: money(inv.tax, cur) })
    if (num(inv.retention)) facts.push({ label: 'Retención de garantía', cents: inv.retention, currency: cur })
    for (const d of Array.isArray(inv.deductions) ? inv.deductions : []) facts.push({ label: `Deducción ${String(d.code ?? '')}`.trim(), cents: d.amount, currency: cur })
    facts.push({ label: 'A cobrar', cents: inv.payable, currency: cur })
    if (inv.face) facts.push({ label: 'FACe (DIR3)', mono: [inv.face.oficina_contable, inv.face.organo_gestor, inv.face.unidad_tramitadora].join(' · ') })
  }
  return { headline, facts }
}

function arCashSummary({ item, rows, core }: SummaryInput): ReasoningSummary {
  const row = (rows[0] ?? {}) as Partial<ArCashRow>
  const cur = item.currency ?? 'EUR'
  const apps = Array.isArray(row.applications) ? row.applications : []
  const residuals = Array.isArray(row.residuals) ? row.residuals : []
  const customer = row.customer ? core.customers?.find((c) => c.id === row.customer) : undefined
  const line = findBankLine(core, item.key)
  const amount = money(line?.amount ?? item.amount, cur)
  const residualText = residuals
    .map((r) => {
      const e = AR_RESIDUAL_CATALOG[r.type as keyof typeof AR_RESIDUAL_CATALOG]
      const what = r.type === 'NON_CUSTOMER' && r.account && NON_CUSTOMER_KIND[r.account] ? NON_CUSTOMER_KIND[r.account] : (e?.label.toLowerCase() ?? r.type)
      return `${what}${r.account ? ` (${r.account})` : ''}`
    })
    .join(', ')
  let headline: string
  if (!row.customer) headline = `El cobro de ${amount} no viene de un cliente${residualText ? `: ${residualText}` : ''}.`
  else if (!apps.length) headline = `Cobro de ${amount} de ${customer?.name ?? row.customer} sin aplicar a facturas abiertas${residualText ? `: ${residualText}` : ''}.`
  else {
    const what = apps.length === 1 ? `la ${apps[0].pagare ? `pagaré ${apps[0].pagare}` : `factura ${apps[0].invoice}`}` : `${apps.length} facturas`
    headline = `Cobro de ${amount} de ${customer?.name ?? row.customer} aplicado a ${what}${residualText ? `; diferencia: ${residualText}` : ''}.`
  }
  const facts: ReasoningFact[] = []
  if (line) facts.push({ label: 'Línea bancaria', mono: item.key, text: `${formatDate(line.booking_date)} · ${line.text}` })
  facts.push(row.customer ? { label: 'Cliente', mono: row.customer, text: customer?.name } : { label: 'Cliente', text: 'No es un cliente', tone: 'warn' })
  for (const a of apps) facts.push({ label: a.pagare ? 'Pagaré' : 'Factura', mono: String(a.pagare ?? a.invoice ?? '—'), cents: a.amount, currency: cur })
  for (const r of residuals) {
    const e = AR_RESIDUAL_CATALOG[r.type as keyof typeof AR_RESIDUAL_CATALOG]
    facts.push({ label: e?.label ?? r.type, mono: r.account ?? r.invoice, cents: r.amount, currency: cur, tone: e?.attention ? 'warn' : undefined })
  }
  return { headline, facts }
}

const NON_CUSTOMER_KIND: Record<string, string> = {
  '75900000': 'indemnización de seguro',
  '56500000': 'devolución de fianza',
  '47000000': 'devolución de IVA',
}

function findBankLine(core: DatasetCore, bankLine: string): BankLine | null {
  for (const st of core.bankStatements ?? []) {
    const l = st.lines.find((x) => x.bank_line === bankLine)
    if (l) return l
  }
  return null
}

export function matchShape(bankCount: number, bookCount: number): string {
  if (bankCount === 1 && bookCount === 1) return '1:1'
  if (bookCount === 1) return 'N:1'
  if (bankCount === 1) return '1:N'
  return 'N:M'
}

function bankSummary({ item, rows, core, entries }: SummaryInput): ReasoningSummary {
  const row = (rows[0] ?? {}) as Partial<BankRecRow>
  const account = item.key.split('/')[0]
  const bank = core.bankAccounts?.find((b) => b.id === account)
  const banks = item.evidence.filter((e): e is Extract<EvidenceRef, { kind: 'bank' }> => e.kind === 'bank').map((e) => e.bank_line)
  const books = item.evidence.filter((e): e is Extract<EvidenceRef, { kind: 'journal' }> => e.kind === 'journal').map((e) => e.book_line)
  const category = BANK_CATEGORY_CATALOG[item.outcome as keyof typeof BANK_CATEGORY_CATALOG]
  const adjusted = (Array.isArray(row.adjustments) ? row.adjustments : []).some((a) => String(a.category) === item.outcome)
  let headline: string
  if (banks.length && books.length) {
    const shape = matchShape(banks.length, books.length)
    headline = `Casada ${shape}: ${lines(banks.length, 'línea', 'líneas')} del extracto con ${lines(books.length, 'apunte', 'apuntes')} del libro${category ? `, con ${category.label.toLowerCase()}` : ''}.`
  } else if (banks.length || books.length) {
    const side = banks.length ? 'el extracto' : 'libros'
    headline = `Sin casar en ${side}: ${category?.label.toLowerCase() ?? item.outcome}; ${adjusted ? 'se corrige con un asiento de ajuste' : 'se explica sin ajuste'} (§4).`
  } else headline = `Ajuste sin partida: ${category?.label.toLowerCase() ?? item.outcome} (§4).`
  const facts: ReasoningFact[] = [{ label: 'Cuenta', mono: account, text: [bank?.bank, bank?.gl_account].filter(Boolean).join(' · ') || undefined }]
  const cur = bank?.currency ?? item.currency ?? 'EUR'
  for (const b of banks) {
    const l = findBankLine(core, b)
    facts.push({ label: 'Extracto', mono: b, text: l ? `${formatDate(l.booking_date)} · ${l.text}` : undefined, cents: l?.amount, currency: cur })
  }
  if (books.length) facts.push({ label: books.length === 1 ? 'Apunte' : 'Apuntes', mono: books.length > 4 ? `${books.slice(0, 4).join(', ')} +${books.length - 4}` : books.join(', ') })
  if (category) facts.push({ label: 'Categoría', text: category.label, tone: category.adjustment ? 'info' : 'neutral' })
  if (entries.length) facts.push({ label: 'Ajuste', text: `${lines(lineCount(entries), 'línea', 'líneas')} contra la cuenta ${bank?.gl_account ?? '572'}` })
  return { headline, facts }
}

/** One month of interest on the KMI loan with a day-count basis (act/360 or 30/360). */
export function loanInterest(principal: number, rateBp: number, days: number): number {
  return Math.round((principal * (rateBp / 10_000) * days) / 360)
}

function icSummary({ item, rows, core, entries }: SummaryInput): ReasoningSummary {
  const row = (rows[0] ?? {}) as Partial<IcRow> & Record<string, unknown>
  const [pair, cause] = [item.key.split('/')[0], item.outcome]
  const entry = IC_CAUSE_CATALOG[cause as keyof typeof IC_CAUSE_CATALOG]
  const cur = item.currency ?? 'EUR'
  const responsible = str(row.responsible) ?? item.company
  const amount = num(row.amount) ?? item.amount
  const headline = `Diferencia de ${money(amount, cur)} entre ${pair.replace('-', ' y ')}: ${entry?.label.toLowerCase() ?? cause}. ${
    entries.length ? `Corrige ${responsible} con un asiento de ${lines(lineCount(entries), 'línea', 'líneas')}.` : 'Sin ajuste aquí: se corrige en la conciliación bancaria.'
  }`
  const facts: ReasoningFact[] = [
    { label: 'Pareja', mono: pair.replace('-', ' – ') },
    { label: 'Causa', text: entry?.label ?? cause },
  ]
  if (str(row.account)) facts.push({ label: 'Cuentas', mono: String(row.account) })
  if (str(row.detail)) facts.push({ label: 'Detalle', text: String(row.detail) })
  facts.push({ label: 'Diferencia', cents: amount ?? undefined, currency: cur })
  if (responsible) facts.push({ label: 'Responsable', mono: responsible })
  const loan = core.intercompanyAgreements?.loan
  const month = core.tasks?.close?.month
  if (cause === 'INTEREST_DAY_COUNT' && loan && month) {
    const [y, m] = month.split('-').map(Number)
    const days = new Date(Date.UTC(y, m, 0)).getUTCDate()
    const act = loanInterest(loan.principal, loan.rate_bp, days)
    const thirty = loanInterest(loan.principal, loan.rate_bp, 30)
    facts.push({
      label: 'Intereses act/360',
      text: `${money(loan.principal, 'EUR')} × ${formatPercent(loan.rate_bp / 10_000)} × ${days}/360 = ${money(act, 'EUR')} (con 30/360: ${money(thirty, 'EUR')})`,
    })
  }
  return { headline, facts }
}

function closeSummary({ item, rows, core, entries }: SummaryInput): ReasoningSummary {
  const row = (rows[0] ?? {}) as Record<string, unknown>
  const type = item.outcome
  const entry = CLOSE_TYPE_CATALOG[type as keyof typeof CLOSE_TYPE_CATALOG]
  const cur = item.currency ?? 'EUR'
  const amount = money(item.amount, cur)
  const vendor = str(row.vendor) ? core.vendors?.find((v) => v.id === row.vendor) : undefined
  const customer = str(row.customer) ? core.customers?.find((c) => c.id === row.customer) : undefined
  const facts: ReasoningFact[] = [{ label: 'Tipo', text: entry?.label ?? type }]
  let headline: string
  const firstDebit = entries.flatMap((e) => e.lines).find((l) => (l.debit ?? 0) > 0)
  switch (type) {
    case 'ACCRUAL': {
      headline = `Periodificación de ${amount} para ${vendor?.name ?? String(row.vendor ?? 'el proveedor')}: servicio consumido y no facturado al cierre, estimado con su histórico (±15 %).`
      facts.push({ label: 'Proveedor', mono: str(row.vendor) ?? undefined, text: vendor?.name })
      const period = Array.isArray(row.period) ? row.period.map(String) : null
      if (period?.length === 2) facts.push({ label: 'Periodo de referencia', text: `${formatDate(period[0])} – ${formatDate(period[1])}` })
      if (str(row.invoice)) facts.push({ label: 'Factura de referencia', mono: String(row.invoice) })
      const history = (core.apInvoices ?? []).filter((i) => i.vendor === row.vendor && i.company === item.company)
      if (history.length) {
        const last = history.reduce((a, b) => (a.issue_date > b.issue_date ? a : b))
        const avg = Math.round(history.reduce((s, i) => s + i.net, 0) / history.length)
        facts.push({ label: 'Histórico', text: `${lines(history.length, 'factura', 'facturas')} · base media ${money(avg, cur)} · última ${formatDate(last.issue_date)}` })
      }
      break
    }
    case 'PREPAID': {
      const deferral = (item.amount ?? 0) > 0
      headline = `Gasto anticipado: ${deferral ? 'se difiere a 48000000 la parte no devengada' : 'se imputa al gasto la mensualidad devengada desde 48000000'} (${amount}).`
      if (str(row.invoice)) facts.push({ label: 'Factura', mono: String(row.invoice) })
      facts.push({ label: 'Sentido', text: deferral ? 'Diferimiento (variación positiva de 48000000)' : 'Imputación (variación negativa de 48000000)' })
      const text = entries.map((e) => str(e.header_text)).find(Boolean)
      if (text) facts.push({ label: 'Concepto', text })
      break
    }
    case 'FX_REVAL': {
      const fcur = str(row.currency)
      const foreign = num(row.foreign)
      headline = `Valoración a tipo de cierre de ${String(row.item ?? 'la partida')}: ${foreign !== null && fcur ? `${money(foreign, fcur)} ` : ''}${num(row.rate) !== null ? `al ${formatNumber(Number(row.rate), { decimals: 6 })} ` : ''}→ ${amount} (${(item.amount ?? 0) >= 0 ? 'aumenta' : 'disminuye'} el valor de la partida).`
      facts.push({ label: 'Partida', mono: String(row.item ?? '—') })
      if (fcur && foreign !== null) facts.push({ label: 'Importe en divisa', cents: foreign, currency: fcur })
      if (num(row.rate) !== null) facts.push({ label: 'Tipo SYN-BCE de cierre', mono: formatNumber(Number(row.rate), { decimals: 6 }) })
      break
    }
    case 'BAD_DEBT': {
      const target = num(row.target)
      const previous = num(row.previous)
      headline =
        target !== null && previous !== null
          ? `Deterioro de ${customer?.name ?? String(row.customer)}: provisión necesaria ${money(target, cur)} − anterior ${money(previous, cur)} = ${amount}.`
          : `Deterioro de ${customer?.name ?? String(row.customer)}: ajuste de ${amount} en 49000000.`
      facts.push({ label: 'Cliente', mono: str(row.customer) ?? undefined, text: customer?.name })
      if (customer?.insolvency) facts.push({ label: 'Concurso', text: `Declarado el ${formatDate(customer.insolvency.declared_on)}`, tone: 'danger' })
      if (target !== null) facts.push({ label: 'Provisión necesaria', cents: target, currency: cur })
      if (previous !== null) facts.push({ label: 'Provisión anterior', cents: previous, currency: cur })
      break
    }
    case 'WIP_REVENUE':
      headline = `Obra ejecutada pendiente de certificar (${String(row.billing_item ?? '—')}): Dr 43090000 / Cr 71300000 por ${amount}, con retrocesión el día 1.`
      if (str(row.billing_item)) facts.push({ label: 'Partida de facturación', mono: String(row.billing_item) })
      break
    case 'DOUBTFUL_RECLASS':
      headline = `${customer?.name ?? String(row.customer)} está en concurso: su saldo pasa de 43000000 a 43600000 factura a factura (${amount}).`
      facts.push({ label: 'Cliente', mono: str(row.customer) ?? undefined, text: customer?.name })
      break
    default:
      headline = `${entry?.label ?? type}: ${amount}.`
  }
  facts.push({ label: 'Importe', cents: item.amount ?? undefined, currency: cur })
  if (firstDebit) facts.push({ label: 'Cuenta al debe', mono: firstDebit.account, text: accountLabel(firstDebit.account, core.chartOfAccounts) })
  return { headline, facts }
}

const SUMMARIES = {
  ap: apSummary,
  ar_billing: arBillingSummary,
  ar_cash: arCashSummary,
  bank_rec: bankSummary,
  ic: icSummary,
  close: closeSummary,
} as const

/** Task-specific «why» of an item, in plain Spanish. */
export function reasoningSummary(input: SummaryInput): ReasoningSummary {
  return SUMMARIES[input.item.task](input)
}

// ---------------------------------------------------------------- bank match detail (needs the book lines)
export interface BookLineAmount {
  id: string
  date: string
  /** Debit − credit on the bank GL account (same sign as the statement). */
  amount: number
}

/** «mismo día, importe exacto» / «a 2 días, diferencia de 8,17 €» for a bank match. */
export function bankMatchDetail(bank: readonly Pick<BankLine, 'booking_date' | 'amount'>[], books: readonly BookLineAmount[], currency = 'EUR'): string {
  if (!bank.length || !books.length) return ''
  const bankSum = bank.reduce((s, l) => s + l.amount, 0)
  const bookSum = books.reduce((s, l) => s + l.amount, 0)
  const toDay = (d: string) => Date.parse(`${d.slice(0, 10)}T00:00:00Z`) / 86_400_000
  const bankDays = bank.map((l) => toDay(l.booking_date))
  const gap = Math.max(...books.map((b) => Math.min(...bankDays.map((d) => Math.abs(toDay(b.date) - d)))))
  const when = gap === 0 ? 'mismo día' : `a ${gap} ${gap === 1 ? 'día' : 'días'}`
  const diff = bankSum - bookSum
  const amount = diff === 0 ? 'importe exacto' : `diferencia de ${formatMoney(Math.abs(diff), currency)}`
  return `${when}, ${amount}`
}
