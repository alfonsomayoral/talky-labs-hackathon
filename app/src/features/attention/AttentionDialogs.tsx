import { useEffect, useId, useRef, useState } from 'react'
import { Amount, Button, Dialog, Mono } from '@/components'
import { formatNumber } from '@/lib/format'
import { TASK_LABEL, decisionLabel, kindLabel, reasonLabel, rowKeyLabel, totalsByCurrency, type AttentionRow } from './attentionModel'
import { Totals } from './Totals'
import styles from './AttentionPage.module.css'

interface NoteDialogProps {
  row: AttentionRow | null
  onClose: () => void
  onSave: (row: AttentionRow, note: string) => void
}

export function NoteDialog({ row, onClose, onSave }: NoteDialogProps) {
  const formId = useId()
  return (
    <Dialog
      open={row != null}
      onClose={onClose}
      title="Nota"
      description={row && <Mono>{row.a.item}</Mono>}
      size="sm"
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button type="submit" form={formId} variant="primary">
            Guardar nota
          </Button>
        </>
      }
    >
      {/* Keyed so the draft starts from the saved note of each entry. */}
      {row && <NoteForm key={row.key} id={formId} row={row} onSave={onSave} />}
    </Dialog>
  )
}

function NoteForm({ id, row, onSave }: { id: string; row: AttentionRow; onSave: NoteDialogProps['onSave'] }) {
  const [text, setText] = useState(row.override?.note ?? '')
  const ref = useRef<HTMLTextAreaElement>(null)
  // Dialog focuses its first control (the close button) after mounting; the textarea takes it right after.
  useEffect(() => {
    const t = setTimeout(() => ref.current?.focus())
    return () => clearTimeout(t)
  }, [])
  const save = () => onSave(row, text.trim())
  return (
    <form
      id={id}
      className={styles.noteForm}
      onSubmit={(e) => {
        e.preventDefault()
        save()
      }}
    >
      <textarea
        ref={ref}
        className={styles.textarea}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault()
            save()
          }
        }}
        rows={5}
        placeholder="Qué has comprobado o a quién se lo has pedido…"
        aria-label="Nota"
      />
      <p className={styles.hint}>No cambia la decisión: se exporta con las correcciones en overrides.jsonl.</p>
    </form>
  )
}

const LISTED = 8

interface SimilarDialogProps {
  rows: AttentionRow[] | null
  onClose: () => void
  onConfirm: (rows: AttentionRow[]) => void
}

export function SimilarDialog({ rows, onClose, onConfirm }: SimilarDialogProps) {
  const first = rows?.[0]
  const task = first?.task ?? null
  const decision = first?.a.recommendation?.decision
  const reasons = first?.a.recommendation?.reasons ?? []
  const summary = first && [task ? TASK_LABEL[task] : null, kindLabel(first.a.kind), decision ? decisionLabel(task, decision) : null, ...reasons.map((r) => reasonLabel(task, r))].filter(Boolean).join(' · ')
  return (
    <Dialog
      open={rows != null}
      onClose={onClose}
      title={rows ? `Aceptar la recomendación en ${formatNumber(rows.length)} partidas` : ''}
      description={summary}
      footer={
        rows && (
          <>
            <Button onClick={onClose}>Cancelar</Button>
            <Button variant="primary" onClick={() => onConfirm(rows)}>
              Aceptar {formatNumber(rows.length)}
            </Button>
          </>
        )
      }
    >
      {rows && (
        <div className={styles.similarList}>
          {rows.slice(0, LISTED).map((r) => (
            <div key={r.key} className={styles.similarRow}>
              <Mono className={styles.key} title={r.a.item}>
                {rowKeyLabel(r)}
              </Mono>
              <span className={styles.similarName}>{r.item?.counterparty ?? r.a.title}</span>
              <Amount cents={r.a.impact} currency={r.item?.currency ?? 'EUR'} />
            </div>
          ))}
          {rows.length > LISTED && <p className={styles.hint}>y {formatNumber(rows.length - LISTED)} más</p>}
          <div className={styles.similarTotal}>
            <span>Total</span>
            <Totals totals={totalsByCurrency(rows)} />
          </div>
        </div>
      )}
    </Dialog>
  )
}
