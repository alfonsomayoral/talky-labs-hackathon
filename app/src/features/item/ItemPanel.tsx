// Placeholder — phase 2.C implements the item detail panel (tabs: Resumen, Asiento, Evidencia, Traza, Golden).
// Contract: rendered by the shell's PeekHost when the URL has `?item=<task>:<key>`.
export interface ItemPanelProps {
  itemId: string
  onClose: () => void
}

export default function ItemPanel({ itemId }: ItemPanelProps) {
  return <div>{itemId}</div>
}
