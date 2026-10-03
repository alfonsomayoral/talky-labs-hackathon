import { Link } from 'react-router'
import { Badge } from '@/components'
import type { DatasetMeta, RunBundle, RunStats } from '@/domain/types'
import { formatDateTime, formatNumber } from '@/lib/format'
import { longMonth, RUN_SOURCE_LABEL } from './model'
import styles from './Overview.module.css'

/** Opening sentence with the key number; the golden reference is never presented as agent output. */
export function Hero({ meta, run, stats }: { meta: DatasetMeta; run: RunBundle; stats: RunStats }) {
  const golden = run.source === 'golden'
  const auto = stats.byStatus.AUTO ?? 0
  const sourceLabel = RUN_SOURCE_LABEL[run.source]
  return (
    <header className={styles.hero}>
      <p className={styles.dateLine}>
        Cierre de {longMonth(meta.month)} · Grupo Kalmora · {meta.inventory.companies} sociedades
      </p>
      <h1 className={styles.headline}>
        {golden ? 'La solución de referencia resuelve ' : 'El agente ha resuelto '}
        <strong className={styles.headlineKey}>{formatNumber(auto)}</strong> de {formatNumber(stats.items)} partidas sin intervención.
      </h1>
      <div className={styles.runLine}>
        <Badge variant="outline">{sourceLabel}</Badge>
        {run.label !== sourceLabel && <span className={styles.runLabel}>{run.label}</span>}
        <span>Creada {formatDateTime(run.createdAt)}</span>
        {golden && <span>No es salida del agente: es la solución publicada por los organizadores.</span>}
        <Link to="/ejecuciones" className={styles.textLink} title="También puedes cambiarla en el selector de la barra lateral">
          Cambiar de ejecución
        </Link>
      </div>
    </header>
  )
}
