// Sankey «tipo de documento → decisión». Band widths are document counts; clicking a band or a node filters the list.
import { useMemo } from 'react'
import clsx from 'clsx'
import { toneColor } from '@/components'
import { AP_DECISION_CATALOG, AP_DOCUMENT_TYPE_CATALOG } from '@/domain/catalog/policy'
import { formatNumber } from '@/lib/format'
import { DECISION_TONE, type ApSankey as SankeyData } from './model'
import styles from './Ap.module.css'

export interface SankeySelection {
  type: string | null
  decision: string | null
}

interface Props {
  data: SankeyData
  selection: SankeySelection
  onSelect: (sel: SankeySelection) => void
}

const W = 720
const NODE_W = 10
const GAP = 10
const LABEL_W = 210
const MIN_H = 4

const typeLabel = (k: string) => AP_DOCUMENT_TYPE_CATALOG[k as keyof typeof AP_DOCUMENT_TYPE_CATALOG]?.label ?? k
const decisionLabel = (k: string) => AP_DECISION_CATALOG[k as keyof typeof AP_DECISION_CATALOG]?.label ?? k

interface Box {
  key: string
  y: number
  h: number
  count: number
}

function stack(nodes: { key: string; count: number }[], scale: number): Box[] {
  let y = 0
  return nodes.map((n) => {
    const h = Math.max(MIN_H, n.count * scale)
    const box = { key: n.key, y, h, count: n.count }
    y += h + GAP
    return box
  })
}

export function ApSankey({ data, selection, onSelect }: Props) {
  const layout = useMemo(() => {
    const rows = Math.max(data.types.length, data.decisions.length)
    const height = Math.max(160, rows * 34)
    const scale = data.total ? (height - GAP * (rows - 1) - MIN_H * rows) / data.total : 0
    const left = stack(data.types, scale)
    const right = stack(data.decisions, scale)
    const leftOff = new Map(left.map((b) => [b.key, b.y]))
    const rightOff = new Map(right.map((b) => [b.key, b.y]))
    const x0 = LABEL_W + NODE_W
    const x1 = W - LABEL_W - NODE_W
    const bands = data.links.map((l) => {
      const lb = left.find((b) => b.key === l.type)!
      const rb = right.find((b) => b.key === l.decision)!
      const t = Math.max(1, (l.count / lb.count) * lb.h)
      const r = Math.max(1, (l.count / rb.count) * rb.h)
      const y0 = leftOff.get(l.type)!
      const y1 = rightOff.get(l.decision)!
      leftOff.set(l.type, y0 + t)
      rightOff.set(l.decision, y1 + r)
      const mx = (x0 + x1) / 2
      const d = `M${x0},${y0} C${mx},${y0} ${mx},${y1} ${x1},${y1} L${x1},${y1 + r} C${mx},${y1 + r} ${mx},${y0 + t} ${x0},${y0 + t} Z`
      return { link: l, d }
    })
    const h = Math.max(left.at(-1) ? left.at(-1)!.y + left.at(-1)!.h : 0, right.at(-1) ? right.at(-1)!.y + right.at(-1)!.h : 0)
    return { left, right, bands, height: h }
  }, [data])

  const active = selection.type !== null || selection.decision !== null
  const isOn = (type: string | null, decision: string | null) =>
    (selection.type === null || selection.type === type) && (selection.decision === null || selection.decision === decision)
  const toggle = (sel: SankeySelection) => onSelect(sel.type === selection.type && sel.decision === selection.decision ? { type: null, decision: null } : sel)

  return (
    <svg className={styles.sankey} viewBox={`0 0 ${W} ${layout.height}`} role="group" aria-label="Documentos por tipo y decisión">
      {layout.bands.map(({ link, d }) => (
        <path
          key={`${link.type}>${link.decision}`}
          d={d}
          className={clsx(styles.band, active && !isOn(link.type, link.decision) && styles.dim)}
          style={{ fill: toneColor(DECISION_TONE[link.decision] ?? 'neutral') }}
          onClick={() => toggle({ type: link.type, decision: link.decision })}
        >
          <title>{`${typeLabel(link.type)} → ${decisionLabel(link.decision)}: ${formatNumber(link.count)}`}</title>
        </path>
      ))}
      {layout.left.map((b) => (
        <g
          key={b.key}
          className={clsx(styles.sankeyNode, active && selection.type !== b.key && selection.type !== null && styles.dim)}
          onClick={() => toggle({ type: b.key, decision: null })}
          role="button"
          tabIndex={0}
          aria-pressed={selection.type === b.key && selection.decision === null}
          onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && toggle({ type: b.key, decision: null })}
        >
          <rect x={LABEL_W} y={b.y} width={NODE_W} height={b.h} className={styles.nodeBar} />
          <text x={LABEL_W - 8} y={b.y + b.h / 2} className={styles.nodeLabel} textAnchor="end" dominantBaseline="middle">
            {typeLabel(b.key)} <tspan className={styles.nodeCount}>{formatNumber(b.count)}</tspan>
          </text>
        </g>
      ))}
      {layout.right.map((b) => (
        <g
          key={b.key}
          className={clsx(styles.sankeyNode, active && selection.decision !== b.key && selection.decision !== null && styles.dim)}
          onClick={() => toggle({ type: null, decision: b.key })}
          role="button"
          tabIndex={0}
          aria-pressed={selection.decision === b.key && selection.type === null}
          onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && toggle({ type: null, decision: b.key })}
        >
          <rect x={W - LABEL_W - NODE_W} y={b.y} width={NODE_W} height={b.h} style={{ fill: toneColor(DECISION_TONE[b.key] ?? 'neutral') }} />
          <text x={W - LABEL_W + 8} y={b.y + b.h / 2} className={styles.nodeLabel} dominantBaseline="middle">
            {decisionLabel(b.key)} <tspan className={styles.nodeCount}>{formatNumber(b.count)}</tspan>
          </text>
        </g>
      ))}
    </svg>
  )
}
