// The six tasks in execution order as a horizontal SVG pipeline. Each node shows its state,
// headline count and a status/progress bar; clicking a node opens the task page.
import { useNavigate } from 'react-router'
import { toneColor, type Tone } from '@/components'
import type { TaskKey } from '@/domain/types'
import type { NodeState } from './live'
import { TASK_META } from '@/domain/catalog/labels'
import s from './PipelineDag.module.css'

export interface DagNode {
  task: TaskKey
  state: NodeState
  value: string
  caption: string
  /** Bottom line (duration, last item…). */
  detail?: string
  /** Stacked status bar. */
  segments?: { value: number; tone: Tone; label: string }[]
  /** Simple progress bar 0..1; null = running without a known total. */
  progress?: number | null
}

const W = 140
const H = 116
const GAP = 28
const PAD = 2

export const NODE_STATE: Record<NodeState, { label: string; tone: Tone }> = {
  pending: { label: 'Pendiente', tone: 'neutral' },
  running: { label: 'En curso', tone: 'info' },
  done: { label: 'Terminada', tone: 'ok' },
  failed: { label: 'Fallida', tone: 'danger' },
}

function Bar({ x, y, width, node }: { x: number; y: number; width: number; node: DagNode }) {
  const track = <rect x={x} y={y} width={width} height={4} rx={2} className={s.track} />
  if (node.segments?.length) {
    const total = node.segments.reduce((n, seg) => n + seg.value, 0)
    let at = x
    return (
      <g>
        {track}
        {total > 0 &&
          node.segments.map((seg) => {
            const w = (seg.value / total) * width
            const r = <rect key={seg.label} x={at} y={y} width={w} height={4} fill={toneColor(seg.tone)} />
            at += w
            return r
          })}
      </g>
    )
  }
  if (node.progress === undefined) return track
  if (node.progress === null) return <g>{track}<rect x={x} y={y} width={width * 0.3} height={4} rx={2} className={s.indeterminate} /></g>
  return (
    <g>
      {track}
      <rect x={x} y={y} width={Math.max(0, Math.min(1, node.progress)) * width} height={4} rx={2} fill={toneColor(node.state === 'done' ? 'ok' : 'info')} />
    </g>
  )
}

export function PipelineDag({ nodes, label = 'Tareas del cierre' }: { nodes: DagNode[]; label?: string }) {
  const navigate = useNavigate()
  const width = nodes.length * W + (nodes.length - 1) * GAP + PAD * 2
  const height = H + PAD * 2
  return (
    <div className={s.scroll}>
      <svg className={s.svg} viewBox={`0 0 ${width} ${height}`} style={{ maxWidth: width }} role="group" aria-label={label}>
        <defs>
          <marker id="dag-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" className={s.arrowHead} />
          </marker>
        </defs>
        {nodes.slice(1).map((n, i) => {
          const x1 = PAD + (i + 1) * W + i * GAP
          return <line key={`e-${n.task}`} x1={x1 + 2} y1={PAD + H / 2} x2={x1 + GAP - 3} y2={PAD + H / 2} className={s.edge} markerEnd="url(#dag-arrow)" />
        })}
        {nodes.map((n, i) => {
          const x = PAD + i * (W + GAP)
          const y = PAD
          const meta = TASK_META[n.task]
          const state = NODE_STATE[n.state]
          const open = () => navigate(meta.route)
          return (
            <g
              key={n.task}
              className={s.node}
              data-state={n.state}
              role="link"
              tabIndex={0}
              aria-label={`${i + 1}. ${meta.label}: ${state.label}. ${n.value} ${n.caption}${n.detail ? `. ${n.detail}` : ''}`}
              onClick={open}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  open()
                }
              }}
            >
              <title>{`${meta.label} · ${state.label}`}</title>
              <rect x={x} y={y} width={W} height={H} rx={10} className={s.box} />
              <circle cx={x + 14} cy={y + 18} r={4} fill={toneColor(state.tone)} className={n.state === 'running' ? s.pulse : undefined} />
              <text x={x + 24} y={y + 22} className={s.label}>
                {meta.label}
              </text>
              <text x={x + W - 12} y={y + 22} className={s.step} textAnchor="end">
                {i + 1}
              </text>
              <text x={x + 12} y={y + 52} className={s.value}>
                {n.value}
              </text>
              <text x={x + 12} y={y + 69} className={s.caption}>
                {n.caption}
              </text>
              <Bar x={x + 12} y={y + 80} width={W - 24} node={n} />
              <text x={x + 12} y={y + 104} className={s.detail}>
                {n.detail ?? state.label}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
