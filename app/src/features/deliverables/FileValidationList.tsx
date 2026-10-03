// One expandable row per deliverable file: presence, rows vs tasks/, and every validation finding.
import { useState, type ReactNode } from 'react'
import clsx from 'clsx'
import { ChevronRight, Download } from 'lucide-react'
import { Badge, Button, Mono, type Tone } from '@/components'
import type { FileValidation, TaskKey, ValidationReport } from '@/domain/types'
import { DELIVERABLE_FILES } from '@/domain/types'
import { formatNumber } from '@/lib/format'
import { PIPELINE, TASK_META } from '../runs/taskMeta'
import s from './FileValidationList.module.css'

export type OpenKey = (task: TaskKey, key: string) => (() => void) | null

const KEY_PAGE = 40

export function fileStatus(v: FileValidation): { label: string; tone: Tone } {
  if (!v.present) return { label: 'Ausente', tone: 'danger' }
  if (v.errors.length) return { label: v.errors.length === 1 ? '1 error' : `${formatNumber(v.errors.length)} errores`, tone: 'danger' }
  if (v.warnings.length) return { label: v.warnings.length === 1 ? '1 aviso' : `${formatNumber(v.warnings.length)} avisos`, tone: 'warn' }
  return { label: 'Correcto', tone: 'ok' }
}

function Keys({ task, keys, openKey }: { task: TaskKey; keys: string[]; openKey: OpenKey | null }) {
  const [all, setAll] = useState(false)
  const shown = all ? keys : keys.slice(0, KEY_PAGE)
  return (
    <div className={s.keys}>
      {shown.map((k, i) => {
        const open = openKey?.(task, k)
        return open ? (
          <button key={`${k}-${i}`} type="button" className={s.key} onClick={open} title="Abrir">
            <Mono>{k}</Mono>
          </button>
        ) : (
          <Mono key={`${k}-${i}`} className={s.keyStatic}>
            {k}
          </Mono>
        )
      })}
      {keys.length > KEY_PAGE && (
        <Button size="sm" variant="ghost" onClick={() => setAll((a) => !a)}>
          {all ? 'Ver menos' : `y ${formatNumber(keys.length - KEY_PAGE)} más`}
        </Button>
      )}
    </div>
  )
}

function Group({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return (
    <div className={s.group}>
      <div className={s.groupTitle}>
        {title} <span className={s.count}>{formatNumber(count)}</span>
      </div>
      {children}
    </div>
  )
}

function Findings({ task, v, openKey }: { task: TaskKey; v: FileValidation; openKey: OpenKey }) {
  const groups: ReactNode[] = []
  if (v.missingKeys.length)
    groups.push(
      <Group key="missing" title="Elementos de tasks/ sin fila" count={v.missingKeys.length}>
        <Keys task={task} keys={v.missingKeys} openKey={null} />
      </Group>,
    )
  if (v.duplicateKeys.length)
    groups.push(
      <Group key="dup" title="Claves duplicadas" count={v.duplicateKeys.length}>
        <Keys task={task} keys={v.duplicateKeys} openKey={openKey} />
      </Group>,
    )
  if (v.extraKeys.length)
    groups.push(
      <Group key="extra" title="Filas que no están en tasks/" count={v.extraKeys.length}>
        <Keys task={task} keys={v.extraKeys} openKey={openKey} />
      </Group>,
    )
  if (v.unbalancedEntries.length)
    groups.push(
      <Group key="unbalanced" title="Asientos descuadrados" count={v.unbalancedEntries.length}>
        <Keys task={task} keys={v.unbalancedEntries} openKey={openKey} />
      </Group>,
    )
  if (v.nonIntegerAmounts)
    groups.push(
      <Group key="cents" title="Importes que no son céntimos enteros" count={v.nonIntegerAmounts}>
        {null}
      </Group>,
    )
  if (v.unknownAccounts.length)
    groups.push(
      <Group key="accounts" title="Cuentas fuera del plan" count={v.unknownAccounts.length}>
        <div className={s.keys}>
          {v.unknownAccounts.map((a) => (
            <Mono key={a} className={s.keyStatic}>
              {a}
            </Mono>
          ))}
        </div>
      </Group>,
    )
  if (v.invalidValues.length)
    groups.push(
      <Group key="invalid" title="Valores no permitidos" count={v.invalidValues.length}>
        <ul className={s.lines}>
          {v.invalidValues.slice(0, 100).map((x, i) => {
            const open = openKey(task, x.key)
            return (
              <li key={i}>
                {open ? (
                  <button type="button" className={s.key} onClick={open}>
                    <Mono>{x.key}</Mono>
                  </button>
                ) : (
                  <Mono>{x.key}</Mono>
                )}
                <Mono muted>{x.field}</Mono>
                <span>=</span>
                <Mono>{JSON.stringify(x.value)}</Mono>
              </li>
            )
          })}
          {v.invalidValues.length > 100 && <li className={s.muted}>y {formatNumber(v.invalidValues.length - 100)} más</li>}
        </ul>
      </Group>,
    )
  if (v.warnings.length)
    groups.push(
      <Group key="warnings" title="Avisos" count={v.warnings.length}>
        <ul className={s.lines}>
          {v.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      </Group>,
    )
  if (!v.present) return <p className={s.muted}>No hay fichero: la tarea puntúa 0. {v.expected ? `tasks/ pide ${formatNumber(v.expected)} filas.` : ''}</p>
  if (!groups.length) return <p className={s.muted}>Sin incidencias: filas, claves, asientos, importes, cuentas y valores correctos.</p>
  return (
    <div className={s.findings}>
      {v.errors.length > 0 && <p className={s.errors}>{v.errors.join(' · ')}</p>}
      {groups}
    </div>
  )
}

export function FileValidationList({ validation, openKey, onDownload }: { validation: ValidationReport; openKey: OpenKey; onDownload: (task: TaskKey) => void }) {
  const [open, setOpen] = useState<Set<TaskKey>>(() => new Set(PIPELINE.filter((t) => validation.files[t].errors.length > 0)))
  const toggle = (t: TaskKey) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(t)) next.delete(t)
      else next.add(t)
      return next
    })

  return (
    <ul className={s.list}>
      {PIPELINE.map((t) => {
        const v = validation.files[t]
        const status = fileStatus(v)
        const expanded = open.has(t)
        const panelId = `validation-${t}`
        return (
          <li key={t} className={s.item}>
            <div className={s.row}>
              <button type="button" className={s.toggle} aria-expanded={expanded} aria-controls={panelId} onClick={() => toggle(t)}>
                <ChevronRight aria-hidden className={clsx(s.chevron, expanded && s.open)} />
                <Mono className={s.file}>{DELIVERABLE_FILES[t]}</Mono>
                <span className={s.task}>{TASK_META[t].label}</span>
              </button>
              <Badge tone={status.tone} variant="outline" dot>
                {status.label}
              </Badge>
              <span className={clsx(s.rows, 'tabular')}>
                {v.present ? formatNumber(v.rows) : '—'}
                {v.expected !== null && <span className={s.muted}> / {formatNumber(v.expected)}</span>} filas
              </span>
              <Button size="sm" variant="ghost" leadingIcon={<Download />} disabled={!v.present} onClick={() => onDownload(t)} aria-label={`Descargar ${DELIVERABLE_FILES[t]}`}>
                Descargar
              </Button>
            </div>
            {expanded && (
              <div id={panelId} className={s.panel}>
                <Findings task={t} v={v} openKey={openKey} />
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
