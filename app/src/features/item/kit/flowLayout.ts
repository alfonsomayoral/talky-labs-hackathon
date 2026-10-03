// Geometry of a ProcessMap: columns left → right, nodes stacked top-down, bands sized by count.

import type { Tone } from '@/components'
import type { FlowLink, FlowNode, ProcessFlow } from './processFlow'

export const FLOW_METRICS = {
  titleHeight: 26,
  headerHeight: 50,
  rowHeight: 22,
  annotationHeight: 20,
  nodeGap: 10,
  maxBand: 30,
  minCardWidth: 140,
  maxCardWidth: 220,
  minGap: 28,
  idealGap: 40,
} as const

export interface NodeBox {
  x: number
  y: number
  width: number
  height: number
}

export interface Band {
  id: string
  source: string
  target: string
  count: number
  tone: Tone
  /** SVG path of the band (closed shape). */
  d: string
}

export interface FlowLayout {
  width: number
  height: number
  cardWidth: number
  columns: { x: number; title: string; section: string | null }[]
  boxes: Map<string, NodeBox>
  bands: Band[]
}

export function nodeHeight(n: FlowNode): number {
  const m = FLOW_METRICS
  return m.headerHeight + (n.annotation ? m.annotationHeight : 0) + (n.breakdown.length ? n.breakdown.length * m.rowHeight + 6 : 0)
}

const bandPath = (x1: number, a: number, x2: number, b: number, t: number): string => {
  const xm = (x1 + x2) / 2
  return `M${x1},${a}C${xm},${a} ${xm},${b} ${x2},${b}L${x2},${b + t}C${xm},${b + t} ${xm},${a + t} ${x1},${a + t}Z`
}

/** Lays a flow out for a container `width` (the result may be wider: the map then scrolls). */
export function layoutFlow(flow: ProcessFlow, width: number): FlowLayout {
  const m = FLOW_METRICS
  const n = Math.max(1, flow.columns.length, ...flow.nodes.map((x) => x.column + 1))
  const cardWidth = Math.max(m.minCardWidth, Math.min(m.maxCardWidth, Math.floor((width - (n - 1) * m.idealGap) / n)))
  const gap = n > 1 ? Math.max(m.minGap, (width - n * cardWidth) / (n - 1)) : 0
  const totalWidth = Math.round(n * cardWidth + (n - 1) * gap)

  const boxes = new Map<string, NodeBox>()
  const bottoms: number[] = Array.from({ length: n }, () => m.titleHeight)
  for (const node of flow.nodes) {
    const y = bottoms[node.column]
    const height = nodeHeight(node)
    boxes.set(node.id, { x: Math.round(node.column * (cardWidth + gap)), y, width: cardWidth, height })
    bottoms[node.column] = y + height + m.nodeGap
  }
  const height = Math.max(...bottoms) - m.nodeGap

  const maxCount = Math.max(1, ...flow.nodes.filter((x) => !x.unit).map((x) => x.count))
  const thickness = (count: number) => (count > 0 ? Math.max(2, Math.round((count / maxCount) * m.maxBand)) : 0)
  const byId = new Map(flow.nodes.map((x) => [x.id, x]))
  const outOffset = new Map<string, number>()
  const inOffset = new Map<string, number>()
  const portStart = (id: string, links: { count: number }[]) => {
    const total = links.reduce((s, l) => s + thickness(l.count), 0)
    return boxes.get(id)!.y + Math.max(4, (m.headerHeight - total) / 2)
  }
  const links = flow.links.filter((l) => boxes.has(l.source) && boxes.has(l.target))
  const sorted = [...links].sort((a, b) => boxes.get(a.target)!.y - boxes.get(b.target)!.y || boxes.get(a.source)!.y - boxes.get(b.source)!.y)
  for (const l of sorted) {
    if (!outOffset.has(l.source)) outOffset.set(l.source, portStart(l.source, links.filter((x) => x.source === l.source)))
  }
  const bySourceY = [...links].sort((a, b) => boxes.get(a.source)!.y - boxes.get(b.source)!.y)
  const inPos = new Map<FlowLink, number>()
  for (const l of bySourceY) {
    if (!inOffset.has(l.target)) inOffset.set(l.target, portStart(l.target, links.filter((x) => x.target === l.target)))
    const y = inOffset.get(l.target)!
    inPos.set(l, y)
    inOffset.set(l.target, y + thickness(l.count))
  }
  const bands: Band[] = sorted.map((l) => {
    const t = thickness(l.count)
    const a = outOffset.get(l.source)!
    outOffset.set(l.source, a + t)
    const src = boxes.get(l.source)!
    const dst = boxes.get(l.target)!
    return {
      id: `${l.source}->${l.target}`,
      source: l.source,
      target: l.target,
      count: l.count,
      tone: byId.get(l.target)?.tone ?? 'neutral',
      d: bandPath(src.x + src.width, a, dst.x, inPos.get(l)!, t),
    }
  })

  return {
    width: totalWidth,
    height,
    cardWidth,
    columns: Array.from({ length: n }, (_, i) => ({
      x: Math.round(i * (cardWidth + gap)),
      title: flow.columns[i]?.title ?? '',
      section: flow.columns[i]?.section ?? null,
    })),
    boxes,
    bands,
  }
}
