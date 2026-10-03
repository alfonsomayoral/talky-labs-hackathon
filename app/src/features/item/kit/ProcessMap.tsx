import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import clsx from 'clsx'
import { Amount, Tooltip } from '@/components'
import { formatNumber } from '@/lib/format'
import { FLOW_METRICS, layoutFlow } from './flowLayout'
import type { FlowFilter, FlowLeaf, FlowNode, ProcessFlow } from './processFlow'
import styles from './ProcessMap.module.css'

export interface ProcessMapProps {
  flow: ProcessFlow
  /** Id of the selected node or breakdown entry (its FlowFilter.id). */
  selectedId?: string | null
  /** Click on a node/breakdown entry: its filter, or null when the selected one is clicked again. */
  onSelect?: (filter: FlowFilter | null) => void
  className?: string
  'aria-label'?: string
}

const FALLBACK_WIDTH = 960

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(FALLBACK_WIDTH)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(320, Math.floor(entry.contentRect.width))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}

/**
 * Decision map of a process: the policy stages left → right, items per branch as bands.
 * Each node shows its count, EUR amount and § of the policy; clicking filters a list.
 */
export function ProcessMap({ flow, selectedId, onSelect, className, 'aria-label': ariaLabel }: ProcessMapProps) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const layout = useMemo(() => layoutFlow(flow, width), [flow, width])
  const [hovered, setHovered] = useState<string | null>(null)
  const selectedNode = selectedId ? flow.nodes.find((n) => n.id === selectedId || n.breakdown.some((b) => b.id === selectedId))?.id : null
  const focus = hovered ?? selectedNode ?? null

  const select = (leaf: FlowLeaf) => onSelect?.(leaf.id === selectedId ? null : leaf.filter)

  return (
    <div ref={ref} className={clsx(styles.scroller, className)} role="group" aria-label={ariaLabel ?? `Mapa de decisión: ${flow.title}`}>
      <div className={styles.canvas} style={{ width: layout.width, height: layout.height }}>
        {layout.columns.map((c, i) => (
          <div key={i} className={styles.columnTitle} style={{ left: c.x, width: layout.cardWidth }}>
            {c.section && <span className={styles.columnSection}>{c.section}</span>}
            <span className={styles.columnText}>{c.title}</span>
          </div>
        ))}
        <svg className={styles.bands} width={layout.width} height={layout.height} aria-hidden>
          {layout.bands.map((b) => (
            <path key={b.id} d={b.d} className={clsx(styles.band, focus && (b.source === focus || b.target === focus) && styles.bandActive)} data-tone={b.tone}>
              <title>{formatNumber(b.count)}</title>
            </path>
          ))}
        </svg>
        {flow.nodes.map((n) => {
          const box = layout.boxes.get(n.id)!
          return (
            <MapNode
              key={n.id}
              node={n}
              columnSection={layout.columns[n.column]?.section ?? null}
              style={{ left: box.x, top: box.y, width: box.width, height: box.height }}
              selectedId={selectedId ?? null}
              onSelect={onSelect ? select : undefined}
              onHover={setHovered}
            />
          )
        })}
      </div>
    </div>
  )
}

interface MapNodeProps {
  node: FlowNode
  /** The column title already shows it: the node only repeats a different section. */
  columnSection: string | null
  style: CSSProperties
  selectedId: string | null
  onSelect?: (leaf: FlowLeaf) => void
  onHover: (id: string | null) => void
}

function MapNode({ node, columnSection, style, selectedId, onSelect, onHover }: MapNodeProps) {
  const empty = node.count === 0
  const clickable = !!onSelect && !node.unit && !empty
  const selected = selectedId === node.id
  const head = (
    <>
      <span className={styles.label}>{node.label}</span>
      <span className={styles.figures}>
        <span className={clsx(styles.count, 'tabular')}>
          {formatNumber(node.count)}
          {node.unit && <span className={styles.unit}> {node.unit}</span>}
        </span>
        <span className={styles.side}>
          {node.section && <span className={clsx(styles.section, node.section === columnSection && styles.sectionQuiet)}>{node.section}</span>}
          {node.amount > 0 && <Amount cents={node.amount} compact className={styles.amount} />}
        </span>
      </span>
    </>
  )
  const headEl = clickable ? (
    <button type="button" className={clsx(styles.head, styles.clickable)} aria-pressed={selected} onClick={() => onSelect?.(node)}>
      {head}
    </button>
  ) : (
    <div className={styles.head}>{head}</div>
  )
  return (
    <div
      className={clsx(styles.node, selected && styles.selected, empty && styles.empty)}
      data-tone={node.tone}
      style={{ ...style, ['--row-h' as string]: `${FLOW_METRICS.rowHeight}px`, ['--head-h' as string]: `${FLOW_METRICS.headerHeight}px` }}
      onPointerEnter={() => onHover(node.id)}
      onPointerLeave={() => onHover(null)}
    >
      {node.description ? <Tooltip content={node.description}>{headEl}</Tooltip> : headEl}
      {node.annotation && <p className={styles.annotation}>{node.annotation}</p>}
      {node.breakdown.length > 0 && (
        <ul className={styles.breakdown}>
          {node.breakdown.map((b) => (
            <li key={b.id}>
              <BreakdownRow leaf={b} selected={selectedId === b.id} onSelect={onSelect} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function BreakdownRow({ leaf, selected, onSelect }: { leaf: FlowLeaf; selected: boolean; onSelect?: (leaf: FlowLeaf) => void }) {
  const content = (
    <>
      <span className={styles.dot} data-tone={leaf.tone} aria-hidden />
      <span className={styles.rowLabel}>{leaf.label}</span>
      <span className={clsx(styles.rowCount, 'tabular')}>{formatNumber(leaf.count)}</span>
    </>
  )
  const row =
    onSelect && leaf.count > 0 ? (
      <button type="button" className={clsx(styles.row, styles.clickable, selected && styles.rowSelected)} aria-pressed={selected} onClick={() => onSelect(leaf)}>
        {content}
      </button>
    ) : (
      <div className={styles.row}>{content}</div>
    )
  const tip = [leaf.section, leaf.description].filter(Boolean).join(' · ')
  return tip ? <Tooltip content={tip}>{row}</Tooltip> : row
}
