// Minimal trace rebuilt from the deliverables when the run has no trace/events.jsonl.
// Every event carries ts = run.createdAt and no duration: it is a reconstruction, not a log.

import type { AgentEvent, ApRow, DatasetCore, EventKind, EventResult, EvidenceRef, RunBundle, WorkItem } from '@/domain/types'
import {
  AP_ACTION_CATALOG,
  AP_CASCADE,
  AP_DECISION_CATALOG,
  AP_DOCUMENT_TYPE_CATALOG,
  AP_PAYEE_CATALOG,
  AP_REASON_CATALOG,
  outcomeEntry,
  reasonEntry,
  type CascadeGroup,
} from '@/domain/catalog/policy'
import { effectiveDeliverables, entryImbalance } from '../ledger/entries'
import { buildItems } from './items'

type Step = Omit<AgentEvent, 'event_id' | 'item' | 'seq' | 'ts'>

const step = (kind: EventKind, name: string, result: EventResult, summary: string, policy_ref: string | null, evidence?: EvidenceRef[]): Step => ({
  kind,
  step: name,
  result,
  summary,
  policy_ref,
  ...(evidence?.length ? { evidence } : {}),
  model: null,
  confidence: null,
})

const DECISION_GROUP: Record<string, CascadeGroup> = {
  DUPLICATE: 'duplicate',
  REJECT: 'reject',
  HOLD: 'hold',
  POST_PAYMENT_BLOCK: 'payment_block',
  POST: 'post',
}
const GROUP_ORDER: CascadeGroup[] = ['duplicate', 'reject', 'hold', 'payment_block', 'post']

const reasonLabel = (r: string) => AP_REASON_CATALOG[r as keyof typeof AP_REASON_CATALOG]?.label ?? r

/** §2.2 cascade: PASS until the first failing check, then FAIL and stop. */
function apCascade(row: ApRow, item: WorkItem): Step[] {
  const decision = String(row.decision)
  const out: Step[] = []
  if (decision === 'NOT_INVOICE') {
    const type = AP_DOCUMENT_TYPE_CATALOG[row.document_type]
    out.push(step('CLASSIFY', 'document_type', 'INFO', `${type?.label ?? String(row.document_type)}: no es una factura`, '§2.1', item.evidence.slice(0, 2)))
    return out
  }
  const group = DECISION_GROUP[decision]
  if (!group) return out
  const reasons = [...item.reasons, ...(row.payment_block ? [String(row.payment_block)] : []), ...(decision === 'DUPLICATE' ? ['DUPLICATE'] : [])]
  const failing = AP_CASCADE.find((s) => s.group === group && reasons.includes(s.code))
  const stopAt = GROUP_ORDER.indexOf(group)
  for (const s of AP_CASCADE) {
    if (s.group === 'post') break
    if (failing && s === failing) {
      const detail = s.code === 'DUPLICATE' ? `duplicado de ${String(row.duplicate_of ?? '¿?')}` : reasonLabel(s.code)
      out.push(step('CHECK', s.step, 'FAIL', `${s.label}: ${detail}`, s.section))
      return out
    }
    if (!failing && GROUP_ORDER.indexOf(s.group) === stopAt) {
      const label = AP_DECISION_CATALOG[decision as keyof typeof AP_DECISION_CATALOG].label
      out.push(step('CHECK', group, 'FAIL', `${label}: ${reasons.map(reasonLabel).join(', ') || 'sin motivo'}`, s.section))
      return out
    }
    out.push(step('CHECK', s.step, 'PASS', `${s.label}: correcto`, s.section))
  }
  return out
}

function apSteps(row: ApRow, item: WorkItem, posted: number, balanced: boolean): Step[] {
  const out = apCascade(row, item)
  if (row.payee && typeof row.payee === 'object') {
    const p = AP_PAYEE_CATALOG[row.payee.type as keyof typeof AP_PAYEE_CATALOG]
    out.push(step('CHECK', 'payee', 'INFO', p?.description ?? String(row.payee.type), '§2.2'))
  }
  const decision = AP_DECISION_CATALOG[row.decision as keyof typeof AP_DECISION_CATALOG]
  const action = row.action ? AP_ACTION_CATALOG[row.action as keyof typeof AP_ACTION_CATALOG] : null
  const reasons = item.reasons.length ? `: ${item.reasons.map(reasonLabel).join(', ')}` : ''
  out.push(step('DECIDE', 'decision', 'INFO', `${decision?.label ?? String(row.decision)}${reasons}${action ? ` · ${action.label}` : ''}`, decision?.section ?? null))
  if (posted) out.push(postStep(posted, balanced, '§2.3'))
  return out
}

const postStep = (lines: number, balanced: boolean, ref: string | null): Step =>
  step('POST', 'journal_entry', balanced ? 'PASS' : 'FAIL', `Asiento de ${lines} ${lines === 1 ? 'línea' : 'líneas'} ${balanced ? 'cuadrado' : 'descuadrado'}`, ref)

function genericSteps(item: WorkItem, posted: number, balanced: boolean): Step[] {
  const outcome = outcomeEntry(item.task, item.outcome)
  const label = outcome?.label ?? item.outcome
  const ref = outcome?.section ?? item.policyRefs[0] ?? null
  const out: Step[] = []
  const firstEvidence = item.evidence.slice(0, 3)
  switch (item.task) {
    case 'ar_billing':
      out.push(step('MATCH', 'contract', 'INFO', item.title, '§3.1', firstEvidence))
      break
    case 'ar_cash': {
      out.push(step('MATCH', 'customer', item.counterparty ? 'PASS' : 'INFO', item.counterparty ? `Cliente ${item.counterparty}` : 'El cobro no viene de un cliente', '§3.2', firstEvidence))
      const residuals = item.reasons.map((r) => reasonEntry('ar_cash', r)?.label ?? r)
      if (residuals.length) out.push(step('MATCH', 'residuals', 'INFO', `Diferencias: ${residuals.join(', ')}`, '§3.2'))
      break
    }
    case 'bank_rec': {
      const matched = item.outcome === 'MATCH' || (item.evidence.some((e) => e.kind === 'bank') && item.evidence.some((e) => e.kind === 'journal'))
      out.push(step('MATCH', 'match', matched ? 'PASS' : 'FAIL', matched ? item.title : 'Sin contrapartida en el otro lado', '§4', firstEvidence))
      break
    }
    case 'ic':
      out.push(step('MATCH', 'pair', 'FAIL', `Diferencia entre ${item.key.split('/')[0].replace('-', ' y ')}`, '§6', firstEvidence))
      break
    case 'close':
      if (item.outcome === 'ACCRUAL' || item.outcome === 'BAD_DEBT' || item.outcome === 'FX_REVAL') {
        out.push(step('ESTIMATE', 'amount', 'INFO', `Importe estimado para ${label.toLowerCase()}`, ref, firstEvidence))
      }
      break
    default:
      break
  }
  out.push(step('DECIDE', 'decision', 'INFO', label, ref))
  if (posted) out.push(postStep(posted, balanced, ref))
  return out
}

/** One minimal trace per item, in item order; seq restarts at 1 per item. */
export function synthesizeEvents(core: DatasetCore, run: RunBundle, items: readonly WorkItem[]): AgentEvent[] {
  const { entries } = buildItems(core, run)
  const ap = effectiveDeliverables(run).ap
  const out: AgentEvent[] = []
  for (const item of items) {
    const es = entries.get(item.id) ?? []
    const lines = es.reduce((s, e) => s + e.lines.length, 0)
    const balanced = es.every((e) => entryImbalance(e).size === 0)
    const steps = item.task === 'ap' && ap[item.rowIndex] ? apSteps(ap[item.rowIndex], item, lines, balanced) : genericSteps(item, lines, balanced)
    steps.forEach((s, i) => {
      out.push({ ...s, event_id: `syn-${String(out.length + 1).padStart(5, '0')}`, item: item.id, seq: i + 1, ts: run.createdAt })
    })
  }
  return out
}
