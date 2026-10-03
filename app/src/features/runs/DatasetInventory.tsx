// What was detected in a phase folder: one compact tile per input family, plus the load warnings.
import { TriangleAlert } from 'lucide-react'
import clsx from 'clsx'
import type { DatasetInventory as Inventory } from '@/domain/types'
import { formatMonth, formatNumber } from '@/lib/format'
import s from './DatasetInventory.module.css'

const FORMAT_LABEL: Record<string, string> = { n43: 'N43', camt053: 'CAMT.053', csv: 'CSV' }

const breakdown = (counts: Record<string, number>, label: (k: string) => string = (k) => k) =>
  Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${label(k)} ${formatNumber(v)}`)
    .join(' · ') || '—'

export const formatBytes = (bytes: number) =>
  bytes >= 1024 * 1024 ? `${formatNumber(bytes / 1024 / 1024, { decimals: 1 })} MB` : `${formatNumber(Math.ceil(bytes / 1024))} KB`

export function DatasetInventory({ inventory: inv }: { inventory: Inventory }) {
  const months = inv.journalMonths
  const tiles = [
    { label: 'Sociedades', value: formatNumber(inv.companies) },
    { label: 'Documentos AP', value: formatNumber(inv.apDocuments), comparison: breakdown(inv.apByChannel) },
    { label: 'Facturación', value: formatNumber(inv.arBillingItems), comparison: 'partidas a facturar' },
    { label: 'Avisos de cobro', value: formatNumber(inv.arRemittanceFiles), comparison: `remesas y FACe · ${formatNumber(inv.arNotices)} penalidades` },
    { label: 'Cuentas bancarias', value: formatNumber(inv.bankAccounts), comparison: breakdown(inv.statementsByFormat, (k) => FORMAT_LABEL[k] ?? k) },
    {
      label: 'Diario',
      value: formatBytes(inv.journalBytes),
      comparison: months.length ? `${formatMonth(months[0])} → ${formatMonth(months.at(-1))} · ${months.length} meses` : 'sin meses',
    },
    { label: 'Referencia (golden)', value: inv.hasGolden ? 'Sí' : 'No', comparison: inv.hasGolden ? 'se puede calcular la nota' : 'sin nota' },
    { label: 'Ficheros', value: formatNumber(inv.files), comparison: formatBytes(inv.bytes) },
  ]
  return (
    <div className={s.wrap}>
      <div className={s.grid}>
        {tiles.map((t) => (
          <div key={t.label} className={s.tile}>
            <div className={s.label}>{t.label}</div>
            <div className={clsx(s.value, 'tabular')}>{t.value}</div>
            {t.comparison && <div className={s.detail}>{t.comparison}</div>}
          </div>
        ))}
      </div>
      {inv.warnings.length > 0 && (
        <div className={s.warnings} role="status">
          <div className={s.warnTitle}>
            <TriangleAlert aria-hidden />
            {inv.warnings.length === 1 ? '1 aviso al cargar' : `${formatNumber(inv.warnings.length)} avisos al cargar`}
          </div>
          <ul>
            {inv.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
