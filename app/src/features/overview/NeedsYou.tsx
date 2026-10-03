import { useMemo } from 'react'
import { Link } from 'react-router'
import { ArrowRight, CircleCheck } from 'lucide-react'
import { Amount, ButtonLink, Card, EmptyState, KeyValue, Mono, PriorityBadge, type KeyValueItem } from '@/components'
import type { AttentionItem, DerivedRun, RunBundle } from '@/domain/types'
import { sortAttention } from '@/engine'
import { formatDateTime, formatDuration, formatMoney, formatNumber } from '@/lib/format'
import { useOpenItem } from '@/shell/useOpenItem'
import { eur, RUN_SOURCE_LABEL, type AttentionSummary } from './model'
import styles from './Overview.module.css'

const TOP = 5

/** First five pending attention items (priority, then impact); each opens the peek. */
export function NeedsYou({ data, pending, attention }: { data: DerivedRun; pending: AttentionItem[]; attention: AttentionSummary }) {
  const openItem = useOpenItem()
  const top = useMemo(() => sortAttention(pending).slice(0, TOP), [pending])
  return (
    <Card
      title="Te necesitan"
      description={attention.count > 0 ? `${formatNumber(attention.count)} partidas · ${eur(attention.impactEur)}` : undefined}
      actions={
        attention.count > 0 && (
          <ButtonLink to="/atencion" variant="ghost" size="sm" trailingIcon={<ArrowRight aria-hidden />}>
            Ver todo ({formatNumber(attention.count)})
          </ButtonLink>
        )
      }
      padding="none"
    >
      {top.length === 0 ? (
        <EmptyState size="sm" icon={<CircleCheck />} title="Nada pendiente" description="Ninguna partida necesita a una persona." />
      ) : (
        <ul className={styles.needs}>
          {top.map((a) => {
            const item = data.itemsById.get(a.item)
            return (
              <li key={`${a.attention_id}|${a.item}`}>
                <button type="button" className={styles.needRow} onClick={() => openItem(a.item)}>
                  <PriorityBadge priority={a.priority} />
                  <span className={styles.needText}>
                    <span className={styles.needTitle}>{a.title}</span>
                    <span className={styles.needSub}>
                      <Mono muted>{item?.key ?? a.item}</Mono>
                      {item?.counterparty && <span> · {item.counterparty}</span>}
                    </span>
                  </span>
                  <Amount cents={a.impact} currency={item?.currency ?? 'EUR'} compact />
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

/** Where these results come from: source, dates and the manifest summary. */
export function LastRun({ run }: { run: RunBundle }) {
  const m = run.manifest
  const items: KeyValueItem[] = [
    { label: 'Origen', value: RUN_SOURCE_LABEL[run.source] },
    { label: 'Ejecución', value: run.label },
    { label: 'Creada', value: formatDateTime(run.createdAt) },
  ]
  if (m) {
    if (m.agent_version) items.push({ label: 'Agente', value: m.agent_version, mono: true })
    if (m.finished_at) items.push({ label: 'Terminó', value: formatDateTime(m.finished_at) })
    if (m.runtime_s != null) items.push({ label: 'Duración', value: formatDuration(m.runtime_s * 1000) })
    if (m.models?.length) items.push({ label: 'Modelos', value: m.models.map((x) => x.name).join(', ') })
    if (m.cost_usd_total != null) items.push({ label: 'Coste', value: formatMoney(Math.round(m.cost_usd_total * 100), 'USD') })
    if (m.human_overrides != null) items.push({ label: 'Correcciones', value: formatNumber(m.human_overrides) })
  }
  return (
    <Card
      title="Última ejecución"
      actions={
        <Link to="/ejecuciones" className={styles.textLink}>
          Ejecuciones
        </Link>
      }
    >
      <KeyValue items={items} labelWidth={96} />
      {!m && (
        <p className={styles.muted}>
          {run.source === 'golden' ? 'La referencia no trae manifiesto: sin coste, modelos ni tiempos.' : 'El paquete no trae manifest.json: sin coste, modelos ni tiempos.'}
        </p>
      )}
    </Card>
  )
}
