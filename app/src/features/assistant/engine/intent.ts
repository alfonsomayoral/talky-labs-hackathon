// Intent recognition with plain rules: ids first (regex), then keywords. No models.

import { TASK_KEYS, type TaskKey } from '@/domain/types'
import type { Intent } from './types'

/** Lowercase without accents, so «Cómo» and «como» match the same rule. */
export const normalize = (s: string): string =>
  s
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()

const FULL_ID = new RegExp(`\\b((?:${TASK_KEYS.join('|')}):[^\\s,;?¿!¡]+)`)
const BANK_ACCOUNT = /\b(BIN-\d+)(\/[^\s,;?¿!¡]+)?/i
/** Letters followed by at least three digits: API004128, BL0000085, F2026-0012. */
const ITEM_TOKEN = /\b([A-Za-z]{1,6}[-_]?\d{3,}[\w\-/~]*)/

const TASK_WORDS: [TaskKey, RegExp][] = [
  ['ap', /\b(proveedor|proveedores|bandeja|ap|facturas? recibidas|compras)\b/],
  ['ar_billing', /\b(facturacion|facturar|factura a clientes|certificaciones?)\b/],
  ['ar_cash', /\b(cobros?|abonos?|555)\b/],
  ['bank_rec', /\b(bancos?|bancari[ao]s?|conciliacion bancaria)\b/],
  ['ic', /\b(intragrupo|intercompany|ic)\b/],
  ['close', /\b(periodificacion(es)?|provision(es)?|deterioro|partidas de cierre|devengos?|anticipados?|cierre contable)\b/],
]

const PROCESS = /(como (ha )?(decidido|decide|decidio|resuelto|resolvio|razonado)|como (se )?(ha )?(procesado|tratado)|proceso|mapa de decision|caminos?)/
const COST = /\b(coste|costes|costado|cuesta|cuanto ha costado|tokens?|modelos?|precio|gasto)\b/
const BALANCE = /(balance|cuadra|descuadr|hueco|sumas y saldos)/
const REVIEW = /(revisar|revision|pendiente|atencion|necesit|aprobar|que hago|que tengo que)/
const SUMMARY = /(resumen|resume|como ha ido|ultimo mes|mes contable|cierre|en general)/

export function taskIn(text: string): TaskKey | null {
  return TASK_WORDS.find(([, re]) => re.test(text))?.[0] ?? null
}

export function detectIntent(question: string): Intent {
  const raw = question.trim()
  const q = normalize(raw)

  const full = raw.match(FULL_ID)
  if (full) return { kind: 'explain', token: full[1] }
  const bank = raw.match(BANK_ACCOUNT)
  if (bank) return bank[2] ? { kind: 'explain', token: `${bank[1].toUpperCase()}${bank[2]}` } : { kind: 'bank', account: bank[1].toUpperCase() }
  const token = raw.match(ITEM_TOKEN)
  if (token) return { kind: 'explain', token: token[1] }

  if (COST.test(q)) return { kind: 'cost' }
  if (PROCESS.test(q)) return { kind: 'process', task: taskIn(q) }
  if (BALANCE.test(q)) return { kind: 'balance' }
  const task = taskIn(q)
  if (task === 'bank_rec' && !REVIEW.test(q)) return { kind: 'bank', account: null }
  if (REVIEW.test(q)) return { kind: 'review' }
  if (SUMMARY.test(q)) return { kind: 'summary' }
  if (task) return { kind: 'process', task }
  return { kind: 'unknown' }
}
