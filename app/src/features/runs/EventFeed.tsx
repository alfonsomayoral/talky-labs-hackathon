// Agent events, newest first. Stays pinned to the newest one while the user is at the top.
import { useLayoutEffect, useRef, useState } from 'react'
import { ArrowUp } from 'lucide-react'
import { Button, Mono, StatusDot, type Tone } from '@/components'
import type { AgentEvent, EventResult } from '@/domain/types'
import { formatNumber } from '@/lib/format'
import s from './EventFeed.module.css'

const RESULT_TONE: Record<EventResult, Tone> = { PASS: 'ok', FAIL: 'danger', INFO: 'neutral' }
const RESULT_LABEL: Record<EventResult, string> = { PASS: 'Correcto', FAIL: 'Falla', INFO: 'Información' }
const PAGE = 200

const time = (ts: string) => {
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' })
}

export function EventFeed({ events, onOpenItem, total }: { events: AgentEvent[]; onOpenItem: (item: string) => void; total?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const [pinned, setPinned] = useState(true)
  const [limit, setLimit] = useState(PAGE)
  const newest = events[0]?.event_id

  useLayoutEffect(() => {
    if (pinned && ref.current) ref.current.scrollTop = 0
  }, [newest, pinned])

  const shown = events.slice(0, limit)
  return (
    <div className={s.wrap}>
      <div
        ref={ref}
        className={s.list}
        role="log"
        aria-live="polite"
        aria-label="Eventos del agente"
        onScroll={(e) => setPinned(e.currentTarget.scrollTop < 8)}
      >
        {shown.map((e) => (
          <div key={e.event_id} className={s.row}>
            <span className={s.time}>{time(e.ts)}</span>
            <StatusDot tone={RESULT_TONE[e.result] ?? 'neutral'} label={RESULT_LABEL[e.result] ?? e.result} />
            <span className={s.kind}>{e.kind}</span>
            <button type="button" className={s.item} onClick={() => onOpenItem(e.item)} title="Abrir la partida">
              <Mono>{e.item}</Mono>
            </button>
            <span className={s.summary} title={e.summary}>
              {e.summary || e.step}
            </span>
            {e.policy_ref ? <Mono muted>{e.policy_ref}</Mono> : <span />}
          </div>
        ))}
        {events.length > limit && (
          <div className={s.more}>
            <Button size="sm" variant="ghost" onClick={() => setLimit((l) => l + PAGE)}>
              Mostrar {formatNumber(Math.min(PAGE, events.length - limit))} más
            </Button>
          </div>
        )}
      </div>
      <div className={s.footer}>
        <span>
          {formatNumber(shown.length)} de {formatNumber(total ?? events.length)} eventos
        </span>
        {!pinned && (
          <Button size="sm" variant="ghost" leadingIcon={<ArrowUp />} onClick={() => setPinned(true)}>
            Ir al último
          </Button>
        )}
      </div>
    </div>
  )
}
