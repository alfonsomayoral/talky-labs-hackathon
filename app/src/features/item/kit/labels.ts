// Spanish labels, routes and icons shared by the item panel, Actividad and the task views.

import {
  BookOpen,
  Calculator,
  CalendarCheck,
  FileSearch,
  FileText,
  Gavel,
  HandCoins,
  Landmark,
  Link2,
  Network,
  Receipt,
  ShieldCheck,
  Sparkles,
  Tags,
  UserPen,
  type LucideIcon,
} from 'lucide-react'
import type { EventKind, EvidenceRef, ItemId, TaskKey } from '@/domain/types'
import { parseItemId } from '@/engine'

export interface TaskMeta {
  /** Sidebar label. */
  label: string
  /** Page title of the task view. */
  title: string
  route: string
  icon: LucideIcon
}

export const TASK_META: Record<TaskKey, TaskMeta> = {
  ap: { label: 'Bandeja AP', title: 'Bandeja de proveedores', route: '/tareas/ap', icon: FileText },
  ar_billing: { label: 'Facturación', title: 'Facturación AR', route: '/tareas/facturacion', icon: Receipt },
  ar_cash: { label: 'Cobros', title: 'Aplicación de cobros', route: '/tareas/cobros', icon: HandCoins },
  bank_rec: { label: 'Bancos', title: 'Conciliación bancaria', route: '/tareas/bancos', icon: Landmark },
  ic: { label: 'Intragrupo', title: 'Conciliación intragrupo', route: '/tareas/intragrupo', icon: Network },
  close: { label: 'Cierre', title: 'Partidas de cierre', route: '/tareas/cierre', icon: CalendarCheck },
}

/** Route of the task view that owns an item, keeping the peek open there (`?item=`). */
export function itemTaskHref(itemId: ItemId): string | null {
  const parsed = parseItemId(itemId)
  if (!parsed) return null
  const base = TASK_META[parsed.task].route
  const account = parsed.task === 'bank_rec' ? parsed.key.split('/')[0] : null
  return `${account ? `${base}/${encodeURIComponent(account)}` : base}?item=${encodeURIComponent(itemId)}`
}

export const EVENT_KIND_META: Record<EventKind, { label: string; icon: LucideIcon }> = {
  EXTRACT: { label: 'Extracción', icon: FileSearch },
  CHECK: { label: 'Comprobación', icon: ShieldCheck },
  MATCH: { label: 'Casación', icon: Link2 },
  CLASSIFY: { label: 'Clasificación', icon: Tags },
  ESTIMATE: { label: 'Estimación', icon: Calculator },
  DECIDE: { label: 'Decisión', icon: Gavel },
  POST: { label: 'Asiento', icon: BookOpen },
  MODEL_CALL: { label: 'Modelo', icon: Sparkles },
  HUMAN_OVERRIDE: { label: 'Corrección humana', icon: UserPen },
}

export const BILLING_TYPE_LABELS: Record<string, string> = {
  OBRA_CERTIFICATION: 'Certificación de obra',
  SERVICE_MONTHLY: 'Servicio mensual',
  PRICE_REVISION: 'Revisión de precios',
  PPA: 'Energía PPA',
  MARKET_SETTLEMENT: 'Liquidación de mercado',
}

const ERP_FILE_LABELS: Record<string, string> = {
  'erp/vendors.jsonl': 'Proveedor',
  'erp/customers.jsonl': 'Cliente',
  'erp/purchase_orders.jsonl': 'Pedido',
  'erp/goods_receipts.jsonl': 'Entrada de mercancía',
  'erp/ap_invoices.jsonl': 'Factura registrada',
  'erp/ap_document_log.jsonl': 'Registro de documentos AP',
  'erp/contractor_certificates.jsonl': 'Certificado art. 43',
  'erp/sales_contracts.jsonl': 'Contrato de venta',
  'erp/ar_invoices.jsonl': 'Factura emitida',
  'erp/promissory_notes.jsonl': 'Pagaré',
  'erp/factoring_assignments.jsonl': 'Cesión a factor',
  'erp/penalty_notices.jsonl': 'Penalidad',
  'erp/intercompany_agreements.json': 'Acuerdos intragrupo',
  'erp/bank_accounts.jsonl': 'Cuenta bancaria',
  'erp/open_items.jsonl': 'Partidas abiertas',
  'erp/fx_rates.jsonl': 'Tipos de cambio',
  'erp/journal_entries.jsonl': 'Asiento',
}

export const erpFileLabel = (file: string): string => ERP_FILE_LABELS[file] ?? file.replace(/^erp\//, '')

/** Stable key of an evidence reference (chips scroll to the matching entry of the Evidencia tab). */
export function evidenceKey(ref: EvidenceRef): string {
  switch (ref.kind) {
    case 'doc':
      return `doc:${ref.path}`
    case 'erp':
      return `erp:${ref.file}:${ref.key}`
    case 'bank':
      return `bank:${ref.account}:${ref.bank_line}`
    case 'journal':
      return `journal:${ref.book_line}`
    case 'precedent':
      return `precedent:${ref.text.slice(0, 80)}`
  }
}

/** Short Spanish label of an evidence reference. */
export function evidenceLabel(ref: EvidenceRef): string {
  switch (ref.kind) {
    case 'doc': {
      const name = ref.path.split('/').pop() ?? ref.path
      return name === 'message.json' ? 'Mensaje recibido' : name
    }
    case 'erp':
      return `${erpFileLabel(ref.file)} ${ref.key}`
    case 'bank':
      return `Línea ${ref.bank_line}`
    case 'journal':
      return `Apunte ${ref.book_line}`
    case 'precedent':
      return 'Precedente histórico'
  }
}
