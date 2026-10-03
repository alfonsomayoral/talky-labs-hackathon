import { memo, useMemo } from 'react'
import { Card, ITEM_STATUS, ITEM_STATUS_ORDER, Tooltip } from '@/components'
import type { RunStats, WorkItem } from '@/domain/types'
import { formatNumber } from '@/lib/format'
import { useActiveItemId, useOpenItem } from '@/shell/useOpenItem'
import { mosaicRows, TASK_META } from './model'
import styles from './Overview.module.css'

/** Every item as a square coloured by status, one row per task. Hover shows the title; click opens the peek. */
export function ItemMosaic({ items, stats }: { items: readonly WorkItem[]; stats: RunStats }) {
  const rows = useMemo(() => mosaicRows(items), [items])
  const openItem = useOpenItem()
  const activeId = useActiveItemId()
  return (
    <Card title="El pulso del cierre" description="Cada cuadro es una partida. Pasa por encima para ver cuál es y pulsa para abrirla.">
      <div className={styles.mosaic}>
        {rows.map((row) => (
          <div key={row.task} className={styles.mosaicRow}>
            <span className={styles.mosaicLabel}>
              {TASK_META[row.task].label}
              <span className="tabular">{formatNumber(row.items.length)}</span>
            </span>
            <MosaicCells items={row.items} activeId={activeId} onOpen={openItem} label={TASK_META[row.task].label} />
          </div>
        ))}
      </div>
      <ul className={styles.legend}>
        {ITEM_STATUS_ORDER.map((s) => (
          <li key={s}>
            <span className={styles.cell} data-tone={ITEM_STATUS[s].tone} aria-hidden />
            {ITEM_STATUS[s].label}
            <span className="tabular">{formatNumber(stats.byStatus[s] ?? 0)}</span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

interface CellsProps {
  items: WorkItem[]
  activeId: string | null
  onOpen: (id: string) => void
  label: string
}

// Squares stay out of the tab order: the same items are reachable by keyboard in Actividad.
const MosaicCells = memo(function MosaicCells({ items, activeId, onOpen, label }: CellsProps) {
  return (
    <div className={styles.mosaicCells} role="group" aria-label={`Partidas de ${label}`}>
      {items.map((it) => (
        <Tooltip key={it.id} content={it.title} delay={60}>
          <button
            type="button"
            tabIndex={-1}
            className={styles.cell}
            data-tone={ITEM_STATUS[it.status].tone}
            data-active={it.id === activeId || undefined}
            aria-label={`${it.title} · ${ITEM_STATUS[it.status].label}`}
            onClick={() => onOpen(it.id)}
          />
        </Tooltip>
      ))}
    </div>
  )
})
