// Attention heuristics (PLAN §5) used when the run has no trace/attention.jsonl.

import type { AttentionItem, AttentionKind, DatasetCore, Deliverables, ItemStatus, Priority, RunBundle, WorkItem } from '@/domain/types'
import {
  AP_ACTION_CATALOG,
  AP_DECISION_CATALOG,
  AP_REASON_CATALOG,
  AR_BILLING_OUTCOME_CATALOG,
  AR_CASH_OUTCOME_CATALOG,
  AR_RESIDUAL_CATALOG,
  BANK_CATEGORY_CATALOG,
  CLOSE_TYPE_CATALOG,
  ESTIMATE_ATTENTION_THRESHOLD_EUR,
  IC_CAUSE_CATALOG,
  type PolicyEntry,
} from '@/domain/catalog/policy'
import { effectiveDeliverables, entryImbalance } from '../ledger/entries'
import { coreIndex, toEur } from './context'
import { buildItems } from './items'

const PRIORITY_ORDER: Record<Priority, number> = { P0: 0, P1: 1, P2: 2, P3: 3 }

const SUGGESTED: Partial<Record<string, string>> = {
  BANK_DETAILS_CHANGED: 'Confirmar el cambio por teléfono con el número de la ficha antes de pagar',
  VENDOR_NOT_IN_MASTER: 'Dar de alta al proveedor y volver a procesar la factura',
  QTY_NOT_RECEIVED: 'Pedir al almacén la entrada de mercancía pendiente',
  PRICE_VARIANCE: 'Revisar el precio con compras o pedir un abono',
  REJECT: 'Pedir al proveedor una factura nueva',
  MASTER_DATA: 'Actualizar el maestro de proveedores con el documento recibido',
  SKIP_PENDING_APPROVAL: 'Seguir la aprobación de la certificación; el cierre registra la obra pendiente',
  NON_CUSTOMER: 'Confirmar el origen del cobro y la cuenta de contrapartida',
  OVERPAYMENT_DUPLICATE: 'Devolver o compensar el pago duplicado con el cliente',
  PARTIAL: 'Reclamar al cliente la diferencia que queda abierta',
  BANK_ERROR: 'Reclamar al banco el cargo duplicado',
  CROSS_TASK: 'Comprobar que la otra tarea refleja el mismo movimiento',
  ESTIMATE: 'Revisar la estimación antes de cerrar',
  UNBALANCED: 'Cuadrar el asiento antes de entregar',
}

interface Candidate {
  item: WorkItem
  kind: AttentionKind
  priority: Priority
  title: string
  entry: PolicyEntry | null
  suggested?: string
}

const fromEntry = (item: WorkItem, entry: PolicyEntry | undefined, title: string, suggested?: string): Candidate | null =>
  entry?.attention ? { item, kind: entry.attention.kind, priority: entry.attention.priority, title, entry, suggested } : null

function apCandidates(item: WorkItem, action: unknown): Candidate[] {
  const out: (Candidate | null)[] = []
  const reasonEntries = item.reasons.map((r) => [r, AP_REASON_CATALOG[r as keyof typeof AP_REASON_CATALOG]] as const)
  const fraud = reasonEntries.find(([, e]) => e?.attention?.priority === 'P0')
  if (fraud) out.push(fromEntry(item, fraud[1], fraud[1].label, SUGGESTED[fraud[0]]))
  else if (item.outcome === 'HOLD' || item.outcome === 'REJECT') {
    const [code, entry] = reasonEntries.find(([, e]) => e) ?? [item.outcome, undefined]
    const decision = AP_DECISION_CATALOG[item.outcome]
    out.push(fromEntry(item, decision, `${decision.label}: ${entry?.label ?? 'sin motivo'}`, SUGGESTED[code] ?? SUGGESTED[item.outcome]))
  }
  if (item.outcome === 'NOT_INVOICE' && typeof action === 'string') {
    const entry = AP_ACTION_CATALOG[action as keyof typeof AP_ACTION_CATALOG]
    out.push(fromEntry(item, entry, entry?.label ?? action, SUGGESTED.MASTER_DATA))
  }
  return out.filter((x): x is Candidate => !!x)
}

function candidates(core: DatasetCore, d: Deliverables, item: WorkItem): Candidate[] {
  const out: (Candidate | null)[] = []
  switch (item.task) {
    case 'ap':
      return apCandidates(item, d.ap[item.rowIndex]?.action)
    case 'ar_billing':
      if (item.outcome === 'SKIP_PENDING_APPROVAL') {
        const e = AR_BILLING_OUTCOME_CATALOG.SKIP_PENDING_APPROVAL
        out.push(fromEntry(item, e, `${e.label}: seguimiento`, SUGGESTED.SKIP_PENDING_APPROVAL))
      }
      break
    case 'ar_cash':
      for (const r of item.reasons) {
        const e = AR_RESIDUAL_CATALOG[r as keyof typeof AR_RESIDUAL_CATALOG]
        out.push(fromEntry(item, e, e?.label ?? r, SUGGESTED[r]))
      }
      if (item.outcome === 'PARTIAL') out.push(fromEntry(item, AR_CASH_OUTCOME_CATALOG.PARTIAL, AR_CASH_OUTCOME_CATALOG.PARTIAL.label, SUGGESTED.PARTIAL))
      break
    case 'bank_rec': {
      const e = BANK_CATEGORY_CATALOG[item.outcome as keyof typeof BANK_CATEGORY_CATALOG]
      out.push(fromEntry(item, e, e?.label ?? item.outcome, item.outcome === 'BANK_ERROR' ? SUGGESTED.BANK_ERROR : SUGGESTED.CROSS_TASK))
      break
    }
    case 'ic': {
      const e = IC_CAUSE_CATALOG[item.outcome as keyof typeof IC_CAUSE_CATALOG]
      out.push(fromEntry(item, e, `${e?.label ?? item.outcome} · ${item.key.split('/')[0]}`, SUGGESTED.CROSS_TASK))
      break
    }
    case 'close': {
      const e = CLOSE_TYPE_CATALOG[item.outcome as keyof typeof CLOSE_TYPE_CATALOG]
      const idx = coreIndex(core)
      const eur = toEur(Math.abs(item.amount ?? 0), item.currency, core.fxRates ?? [], idx.monthEnd)
      if (eur > ESTIMATE_ATTENTION_THRESHOLD_EUR) out.push(fromEntry(item, e, `${e?.label ?? item.outcome} por encima de 50.000 €`, SUGGESTED.ESTIMATE))
      break
    }
  }
  return out.filter((x): x is Candidate => !!x)
}

const lossOf = (a: AttentionItem): number => (typeof a.confidence === 'number' ? (1 - a.confidence) * a.impact : a.impact)

/** Sorts by priority, then expected loss ((1 − p) × impact when p is known, else impact). */
export function sortAttention(items: AttentionItem[]): AttentionItem[] {
  return [...items].sort((a, b) => PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority] || lossOf(b) - lossOf(a))
}

/** Derived attention (derived: true): PLAN §5 rules plus P0 for every unbalanced entry. */
export function deriveAttention(core: DatasetCore, run: RunBundle, items: WorkItem[]): AttentionItem[] {
  const { entries } = buildItems(core, run)
  const d = effectiveDeliverables(run)
  const out: AttentionItem[] = []
  const add = (c: Candidate) =>
    out.push({
      attention_id: '',
      item: c.item.id,
      kind: c.kind,
      priority: c.priority,
      title: c.title,
      impact: Math.abs(c.item.amount ?? c.item.tbImpact),
      affects_tb: c.item.tbImpact > 0,
      policy_ref: c.entry?.section ?? c.item.policyRefs[0] ?? null,
      recommendation: { decision: c.item.outcome, reasons: c.item.reasons },
      alternatives: [],
      suggested_action: c.suggested,
      confidence: c.item.confidence,
      derived: true,
    })
  for (const item of items) {
    const unbalanced = (entries.get(item.id) ?? []).some((e) => entryImbalance(e).size > 0)
    if (unbalanced) {
      add({ item, kind: 'MATERIAL_UNEXPLAINED', priority: 'P0', title: 'Asiento descuadrado: el debe no iguala al haber', entry: null, suggested: SUGGESTED.UNBALANCED })
    }
    for (const c of candidates(core, d, item)) add(c)
  }
  return sortAttention(out).map((a, i) => ({ ...a, attention_id: `att-d${String(i + 1).padStart(4, '0')}` }))
}

/** Items the agent resolved but a person must still look at become NEEDS_HUMAN. */
export function applyAttentionStatus(items: WorkItem[], attention: readonly AttentionItem[]): WorkItem[] {
  const flagged = new Set(attention.map((a) => a.item))
  return items.map((it) => (it.status === 'AUTO' && flagged.has(it.id) ? { ...it, status: 'NEEDS_HUMAN' as ItemStatus } : it))
}
