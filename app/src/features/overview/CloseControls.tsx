import type { ReactNode } from 'react'
import { Info } from 'lucide-react'
import { Amount, Card, Skeleton, StatusDot, Tooltip } from '@/components'
import type { DatasetCore, DerivedRun, RunBundle } from '@/domain/types'
import { formatNumber } from '@/lib/format'
import {
  banksControl,
  deliveryControl,
  eur,
  intercompanyControl,
  pending555,
  TASK_META,
  type ControlTone,
  type ToEur,
} from './model'
import styles from './Overview.module.css'

const RULES = {
  pending:
    'La 55500000 recoge los abonos importados del extracto. La aplicación de cobros (y los cobros sin registrar de bancos) debe dejarla a cero en cada sociedad.',
  banks:
    'Una cuenta está conciliada si está en la entrega y cada diferencia abierta o no necesita ajuste (pago pendiente de cargo, traspaso en tránsito, partida del mes anterior, error del banco) o lleva su ajuste en la sociedad.',
  ic: 'Saldo neto de cada pareja de cuentas intragrupo sumando todas las sociedades, en EUR (3100 al tipo SYN-BCE del último día). Con golden debe coincidir con el neto del balance correcto; sin golden, debe ser cero (±1 €).',
  entries: 'Cada asiento entregado cumple Σ debe = Σ haber.',
  delivery: 'Las seis JSONL están presentes, cubren todas las partidas de tasks/, sin duplicados, con importes en céntimos enteros y cuentas del plan contable.',
}

interface CloseControlsProps {
  data: DerivedRun
  run: RunBundle
  core: DatasetCore
  toEur: ToEur
}

export function CloseControls({ data, run, core, toEur }: CloseControlsProps) {
  const tb = data.trialBalance
  const currencyOf = (company: string) => core.companies.find((c) => c.code === company)?.currency ?? 'EUR'
  const banks = banksControl(core.tasks.bank_accounts, run.deliverables.bank_rec, data.items)
  const delivery = deliveryControl(data.validation)
  const pending = tb ? pending555(tb.rows, toEur) : null
  const ic = tb ? intercompanyControl(tb.rows, toEur) : null
  const unbalanced = data.stats.unbalancedEntries

  return (
    <Card title="Controles de cierre" description="Lo que se comprueba antes de dar el mes por cerrado." padding="none">
      <ul className={styles.controls}>
        <ControlRow
          label="555 pendiente de aplicar"
          rule={RULES.pending}
          tone={pending?.tone}
          value={pending && <Amount cents={pending.afterEur} compact />}
          detail={
            pending &&
            (pending.remaining.length === 0 ? (
              <>Registrado {eur(pending.recordedEur)} → a cero en todas las sociedades</>
            ) : (
              <>
                Con saldo:{' '}
                {pending.remaining.map((r, i) => (
                  <span key={r.company}>
                    {i > 0 && ' · '}
                    {r.company} <Amount cents={r.after} currency={currencyOf(r.company)} compact />
                  </span>
                ))}
              </>
            ))
          }
        />
        <ControlRow
          label="Bancos conciliados"
          rule={RULES.banks}
          tone={banks.tone}
          value={`${banks.reconciled}/${banks.total}`}
          detail={
            banks.missing.length > 0
              ? `Sin entregar: ${banks.missing.join(', ')}`
              : banks.unexplained.length > 0
                ? `Falta un ajuste en ${banks.unexplained.join(', ')}`
                : banks.reconcilingItems > 0
                  ? `${formatNumber(banks.reconcilingItems)} partidas en conciliación sin ajuste (pagos pendientes, tránsitos, mes anterior)`
                  : 'Todas las líneas casadas o ajustadas'
          }
        />
        <ControlRow
          label="Intragrupo neto"
          rule={RULES.ic}
          tone={ic?.tone}
          value={ic && `${ic.pairs.filter((p) => p.tone === 'ok').length}/${ic.pairs.length} ${ic.pairs.some((p) => p.truthEur !== null) ? 'como el correcto' : 'a cero'}`}
          detail={
            ic && (
              <span className={styles.pairs}>
                {ic.pairs.map((p) => (
                  <span key={p.id} title={`${p.accounts.join(' ↔ ')}${p.truthEur !== null ? ` · correcto ${eur(p.truthEur)}` : ''}`}>
                    <StatusDot tone={p.tone} />
                    {p.label} {eur(p.afterEur)}
                  </span>
                ))}
              </span>
            )
          }
        />
        <ControlRow
          label="Asientos cuadrados"
          rule={RULES.entries}
          tone={unbalanced === 0 ? 'ok' : 'danger'}
          value={unbalanced === 0 ? 'Todos' : `${formatNumber(unbalanced)} descuadrados`}
        />
        <ControlRow
          label="Entrega válida"
          rule={RULES.delivery}
          tone={delivery.tone}
          value={delivery.tone === 'ok' ? 'Sí' : `${formatNumber(delivery.errors)} errores`}
          detail={
            delivery.missingFiles.length > 0
              ? `Faltan: ${delivery.missingFiles.map((t) => TASK_META[t].label).join(', ')}`
              : delivery.warnings > 0
                ? `${formatNumber(delivery.warnings)} avisos`
                : undefined
          }
        />
      </ul>
    </Card>
  )
}

interface ControlRowProps {
  label: string
  rule: string
  /** Undefined while the trial balance is still being computed. */
  tone: ControlTone | undefined
  value: ReactNode
  detail?: ReactNode
}

function ControlRow({ label, rule, tone, value, detail }: ControlRowProps) {
  return (
    <li className={styles.control}>
      {tone ? <StatusDot tone={tone} label={tone === 'ok' ? 'Correcto' : tone === 'warn' ? 'Revisar' : 'Falla'} /> : <Skeleton width={8} height={8} radius="50%" />}
      <span className={styles.controlLabel}>
        {label}
        <Tooltip content={rule}>
          <span className={styles.controlRule} tabIndex={0} aria-label={rule}>
            <Info aria-hidden />
          </span>
        </Tooltip>
      </span>
      <span className={styles.controlValue}>{tone ? value : <Skeleton width={64} height={14} />}</span>
      {detail != null && tone && <span className={styles.controlDetail}>{detail}</span>}
    </li>
  )
}
