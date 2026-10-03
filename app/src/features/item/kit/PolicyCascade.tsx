import clsx from 'clsx'
import { Check, Minus, X } from 'lucide-react'
import { AP_REASON_CATALOG } from '@/domain/catalog/policy'
import { Tooltip } from '@/components'
import type { CascadeCheck } from './reasoning'
import styles from './PolicyCascade.module.css'

export interface PolicyCascadeProps {
  /** From `apCascade(row, events)`. */
  checks: CascadeCheck[]
  className?: string
}

const GROUPS: { section: string; title: string }[] = [
  { section: '§2.2.1', title: 'Duplicados' },
  { section: '§2.2.2', title: 'Requisitos' },
  { section: '§2.2.3', title: 'Retención' },
  { section: '§2.2.4', title: 'Pago' },
  { section: '§2.2.5', title: 'Contabilizar' },
]

const STATE_LABEL = { pass: 'Correcto', fail: 'Falla', skipped: 'No evaluado' } as const

/** The §2.2 checks in policy order: ✓ until the one that decides (✗), the rest greyed out. */
export function PolicyCascade({ checks, className }: PolicyCascadeProps) {
  const failing = checks.find((c) => c.state === 'fail')
  const reason = failing ? AP_REASON_CATALOG[failing.step.code as keyof typeof AP_REASON_CATALOG] : undefined
  let n = 0
  return (
    <div className={clsx(styles.cascade, className)}>
      <ol className={styles.groups}>
        {GROUPS.map((g) => {
          const own = checks.filter((c) => c.step.section === g.section)
          if (!own.length) return null
          return (
            <li key={g.section} className={styles.group}>
              <span className={styles.groupTitle}>
                <span className={styles.section}>{g.section}</span>
                {g.title}
              </span>
              <span className={styles.checks}>
                {own.map((c) => {
                  n += 1
                  const Icon = c.state === 'pass' ? Check : c.state === 'fail' ? X : Minus
                  const tip = `${n}. ${c.step.label} — ${STATE_LABEL[c.state]}${c.detail ? `: ${c.detail}` : ''}${c.fromEvent ? ' (evento del agente)' : ''}`
                  return (
                    <Tooltip key={c.step.step} content={tip}>
                      <span className={styles.check} data-state={c.state} aria-label={tip} role="img">
                        <Icon aria-hidden className={styles.icon} />
                        <span className={styles.checkLabel}>{c.step.label}</span>
                      </span>
                    </Tooltip>
                  )
                })}
              </span>
            </li>
          )
        })}
      </ol>
      {failing && (
        <p className={styles.verdict}>
          <X aria-hidden className={styles.verdictIcon} />
          <span>
            <strong>{failing.step.label}</strong>
            {failing.detail ? `: ${failing.detail}` : ''}
            {reason && failing.detail !== reason.description ? <span className={styles.why}> — {reason.description}</span> : null}
          </span>
        </p>
      )}
    </div>
  )
}
