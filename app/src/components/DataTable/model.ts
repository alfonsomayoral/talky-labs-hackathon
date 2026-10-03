// Pure sorting/grouping for DataTable (kept apart so it is testable without a DOM).

export interface SortState {
  columnId: string
  direction: 'asc' | 'desc'
}

export type TableItem<T> = { kind: 'group'; key: string; rows: T[] } | { kind: 'row'; row: T }

const collator = new Intl.Collator('es', { numeric: true, sensitivity: 'base' })

/** Stable sort by a derived value; null/undefined always last regardless of direction. */
export function sortRows<T>(rows: T[], value: (row: T) => string | number | null | undefined, direction: 'asc' | 'desc'): T[] {
  const sign = direction === 'asc' ? 1 : -1
  const decorated = rows.map((row, i) => ({ row, i, v: value(row) }))
  decorated.sort((a, b) => {
    const av = a.v
    const bv = b.v
    if (av == null || bv == null) return av == null && bv == null ? a.i - b.i : av == null ? 1 : -1
    const cmp = typeof av === 'number' && typeof bv === 'number' ? av - bv : collator.compare(String(av), String(bv))
    return cmp !== 0 ? cmp * sign : a.i - b.i
  })
  return decorated.map((d) => d.row)
}

/** Flattens rows into group headers + rows; rows of collapsed groups are left out. */
export function buildItems<T>(
  rows: T[],
  groupBy: ((row: T) => string) | undefined,
  groupOrder: string[] | undefined,
  collapsed: ReadonlySet<string>,
): TableItem<T>[] {
  if (!groupBy) return rows.map((row) => ({ kind: 'row', row }))
  const groups = new Map<string, T[]>()
  for (const row of rows) {
    const key = groupBy(row)
    const list = groups.get(key)
    if (list) list.push(row)
    else groups.set(key, [row])
  }
  const rank = new Map((groupOrder ?? []).map((k, i) => [k, i]))
  const keys = [...groups.keys()].sort((a, b) => {
    const ra = rank.get(a)
    const rb = rank.get(b)
    if (ra != null || rb != null) return (ra ?? Infinity) - (rb ?? Infinity)
    return collator.compare(a, b)
  })
  const items: TableItem<T>[] = []
  for (const key of keys) {
    const groupRows = groups.get(key) ?? []
    items.push({ kind: 'group', key, rows: groupRows })
    if (!collapsed.has(key)) for (const row of groupRows) items.push({ kind: 'row', row })
  }
  return items
}
