// Conversation, composer and preset questions; the page and the ⌘J panel arrange them differently.

import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { ArrowRight, ArrowUp, CalendarCheck, Inbox, ListChecks, Scale, ScanSearch, TriangleAlert, Zap, type LucideIcon } from 'lucide-react'
import { Button, ButtonLink, SegmentedControl, Skeleton } from '@/components'
import { AnswerCards, Citations } from './AnswerCards'
import { assistantProvider, PRESET_QUESTIONS, type ChatMode } from './engine'
import type { Turn } from './store'
import styles from './Assistant.module.css'

const PRESET_ICONS: LucideIcon[] = [CalendarCheck, ListChecks, Scale, Inbox]

const MODES = [
  { value: 'fast' as const, label: 'Rápido', icon: <Zap aria-hidden /> },
  { value: 'deep' as const, label: 'Profundo', icon: <ScanSearch aria-hidden /> },
]

export function Presets({ onAsk, disabled }: { onAsk: (q: string) => void; disabled?: boolean }) {
  return (
    <div className={styles.presets} role="list" aria-label="Preguntas sugeridas">
      {PRESET_QUESTIONS.map((q, i) => {
        const Icon = PRESET_ICONS[i]
        return (
          <button key={q} type="button" role="listitem" className={styles.preset} onClick={() => onAsk(q)} disabled={disabled}>
            <Icon aria-hidden />
            <span>{q}</span>
          </button>
        )
      })}
    </div>
  )
}

interface ComposerProps {
  onAsk: (q: string) => void
  mode: ChatMode
  onModeChange: (mode: ChatMode) => void
  disabled?: boolean
  busy?: boolean
  autoFocus?: boolean
}

export function Composer({ onAsk, mode, onModeChange, disabled, busy, autoFocus }: ComposerProps) {
  const [value, setValue] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (autoFocus) ref.current?.focus({ preventScroll: true })
  }, [autoFocus])

  // Grows with the text up to a few lines.
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
    el.style.overflowY = el.scrollHeight > 160 ? 'auto' : 'hidden'
  }, [value])

  const send = () => {
    const q = value.trim()
    if (!q || disabled || busy) return
    onAsk(q)
    setValue('')
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className={styles.composer}>
      <textarea
        ref={ref}
        className={styles.input}
        rows={1}
        value={value}
        placeholder="Pregunta sobre el cierre: «Explica API004128», «¿Cómo está BIN-1100?»…"
        aria-label="Pregunta al asistente"
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        disabled={disabled}
      />
      <div className={styles.composerBar}>
        <SegmentedControl aria-label="Modo de respuesta" size="sm" options={MODES} value={mode} onChange={onModeChange} />
        <span className={styles.composerHint}>
          {assistantProvider() === 'api' ? 'Responde el backend' : 'Respuestas locales sobre la ejecución activa'} · Mayús+Enter, salto de línea
        </span>
        <Button variant="primary" size="sm" trailingIcon={<ArrowUp aria-hidden />} onClick={send} disabled={disabled || busy || !value.trim()} loading={busy}>
          Enviar
        </Button>
      </div>
    </div>
  )
}

export function Conversation({ turns, onAsk }: { turns: Turn[]; onAsk: (q: string) => void }) {
  const lastRef = useRef<HTMLElement>(null)
  const last = turns.at(-1)
  // A new question, and its answer when it lands, scroll to the question so a long answer is read from the top.
  useEffect(() => {
    lastRef.current?.scrollIntoView({ block: 'start' })
  }, [last?.id, last?.status])

  return (
    <div className={styles.conversation} aria-live="polite">
      {turns.map((t, i) => (
        <article key={t.id} ref={i === turns.length - 1 ? lastRef : undefined} className={styles.turn}>
          <p className={styles.question}>{t.question}</p>
          <TurnAnswer turn={t} onRetry={() => onAsk(t.question)} />
        </article>
      ))}
    </div>
  )
}

function TurnAnswer({ turn, onRetry }: { turn: Turn; onRetry: () => void }) {
  const a = turn.answer
  if (turn.status === 'error') {
    return (
      <div className={styles.error} role="alert">
        <TriangleAlert aria-hidden />
        <span>No se pudo responder: {turn.error}</span>
        <Button size="sm" variant="ghost" onClick={onRetry}>
          Reintentar
        </Button>
      </div>
    )
  }
  if (!a) return <Skeleton lines={3} />
  return (
    <div className={styles.answer}>
      {a.text && <p className={styles.answerText}>{a.text}</p>}
      <AnswerCards cards={a.cards} />
      {turn.status === 'pending' && <Skeleton lines={1} />}
      <Citations citations={a.citations} />
      {a.links.length > 0 && (
        <div className={styles.links}>
          {a.links.map((l) => (
            <ButtonLink key={l.to} to={l.to} variant="ghost" size="sm" trailingIcon={<ArrowRight aria-hidden />}>
              {l.label}
            </ButtonLink>
          ))}
        </div>
      )}
    </div>
  )
}
