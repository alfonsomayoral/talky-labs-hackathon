import { useEffect, useId, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import clsx from 'clsx'
import { ArrowDown, ArrowUp, ChevronRight, SearchX } from 'lucide-react'
import { shouldIgnoreHotkey } from '@/lib/keyboard'
import { formatNumber } from '@/lib/format'
import { EmptyState } from '../EmptyState/EmptyState'
import { buildItems, sortRows, type SortState } from './model'
import styles from './DataTable.module.css'

export type { SortState } from './model'

export interface Column<T> {
  id: string
  header: ReactNode
  cell: (row: T) => ReactNode
  /** Makes the column sortable (click on header). Nulls always sort last. */
  sortValue?: (row: T) => string | number | null | undefined
  /** Grid track: px number or CSS track (`'2fr'`, `'minmax(240px, 1fr)'`). Default `minmax(0, 1fr)`. */
  width?: number | string
  /** Right-align amounts and counts. */
  align?: 'left' | 'right' | 'center'
}

export interface DataTableProps<T> {
  rows: T[]
  columns: Column<T>[]
  getRowId: (row: T) => string
  /** Controlled sort when passed (`null` = original order). */
  sort?: SortState | null
  defaultSort?: SortState | null
  onSortChange?: (sort: SortState | null) => void
  /** Groups rows by this key; sorting applies inside each group. */
  groupBy?: (row: T) => string
  /** Group header content (default: the key). The count is added after it. */
  renderGroup?: (key: string, rows: T[]) => ReactNode
  /** Group keys in display order; unlisted keys follow alphabetically. */
  groupOrder?: string[]
  /** Cursor row (brand-soft highlight, moved with j/k/↑/↓). Controlled when passed. */
  selectedId?: string | null
  onSelectedChange?: (id: string | null) => void
  /** Click or Enter on a row (e.g. open the peek panel). */
  onOpen?: (row: T) => void
  /** j/k work anywhere on the page (not only with the table focused). Use on the page's main list. */
  globalKeys?: boolean
  rowHeight?: number
  /** Fixed height in px. By default the table fills its flex parent (capped at the viewport). */
  height?: number
  empty?: ReactNode
  'aria-label': string
  className?: string
}

const HEADER_HEIGHT = 32
const GROUP_HEIGHT = 32
const FLEX_MIN_WIDTH = 120

function track(width: number | string | undefined): string {
  if (width == null) return 'minmax(0, 1fr)'
  return typeof width === 'number' ? `${width}px` : width
}

/**
 * Virtualized list-table for thousands of rows (36px rows, sticky header).
 * Sort by header click, optional collapsible groups, keyboard cursor (j/k/↑/↓, Enter opens).
 */
export function DataTable<T>({
  rows,
  columns,
  getRowId,
  sort: sortProp,
  defaultSort = null,
  onSortChange,
  groupBy,
  renderGroup,
  groupOrder,
  selectedId: selectedProp,
  onSelectedChange,
  onOpen,
  globalKeys = false,
  rowHeight = 36,
  height,
  empty,
  className,
  ...aria
}: DataTableProps<T>) {
  const uid = useId()
  const scrollRef = useRef<HTMLDivElement>(null)
  const [sortState, setSortState] = useState<SortState | null>(defaultSort)
  const [selectedState, setSelectedState] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set())

  const sort = sortProp !== undefined ? sortProp : sortState
  const selectedId = selectedProp !== undefined ? selectedProp : selectedState

  const setSort = (next: SortState | null) => {
    if (sortProp === undefined) setSortState(next)
    onSortChange?.(next)
  }
  const setSelected = (id: string | null) => {
    if (selectedProp === undefined) setSelectedState(id)
    onSelectedChange?.(id)
  }

  const sorted = useMemo(() => {
    const col = sort ? columns.find((c) => c.id === sort.columnId) : undefined
    return col?.sortValue && sort ? sortRows(rows, col.sortValue, sort.direction) : rows
  }, [rows, columns, sort])

  const items = useMemo(() => buildItems(sorted, groupBy, groupOrder, collapsed), [sorted, groupBy, groupOrder, collapsed])

  const indexById = useMemo(() => {
    const map = new Map<string, number>()
    items.forEach((it, i) => {
      if (it.kind === 'row') map.set(getRowId(it.row), i)
    })
    return map
  }, [items, getRowId])

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => (items[i]?.kind === 'group' ? GROUP_HEIGHT : rowHeight),
    getItemKey: (i) => {
      const it = items[i]
      return it.kind === 'group' ? `g:${it.key}` : `r:${getRowId(it.row)}`
    },
    overscan: 12,
    scrollMargin: HEADER_HEIGHT,
    scrollPaddingStart: HEADER_HEIGHT,
  })

  const move = (delta: 1 | -1) => {
    if (indexById.size === 0) return
    const current = selectedId != null ? indexById.get(selectedId) : undefined
    let i = current ?? (delta === 1 ? -1 : items.length)
    do i += delta
    while (i >= 0 && i < items.length && items[i].kind !== 'row')
    if (i < 0 || i >= items.length) return
    const it = items[i]
    if (it.kind !== 'row') return
    setSelected(getRowId(it.row))
    virtualizer.scrollToIndex(i, { align: 'auto' })
  }

  const openSelected = () => {
    const i = selectedId != null ? indexById.get(selectedId) : undefined
    const it = i != null ? items[i] : undefined
    if (it?.kind === 'row') onOpen?.(it.row)
  }

  // Latest handlers for the window listener without re-subscribing on every render.
  const keysRef = useRef({ move, openSelected })
  useEffect(() => {
    keysRef.current = { move, openSelected }
  })

  useEffect(() => {
    if (!globalKeys) return
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.target instanceof Node && scrollRef.current?.contains(e.target)) || shouldIgnoreHotkey(e)) return
      const onBody = e.target === document.body
      if (e.key === 'j' || (onBody && e.key === 'ArrowDown')) keysRef.current.move(1)
      else if (e.key === 'k' || (onBody && e.key === 'ArrowUp')) keysRef.current.move(-1)
      else if (onBody && e.key === 'Enter') keysRef.current.openSelected()
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [globalKeys])

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (shouldIgnoreHotkey(e.nativeEvent)) return
    if (e.key === 'j' || e.key === 'ArrowDown') move(1)
    else if (e.key === 'k' || e.key === 'ArrowUp') move(-1)
    else if (e.key === 'Enter' && e.target === e.currentTarget) openSelected()
    else return
    e.preventDefault()
  }

  const toggleGroup = (key: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const onHeaderClick = (col: Column<T>) => {
    if (!col.sortValue) return
    if (!sort || sort.columnId !== col.id) setSort({ columnId: col.id, direction: 'asc' })
    else if (sort.direction === 'asc') setSort({ columnId: col.id, direction: 'desc' })
    else setSort(null)
  }

  const gridTemplate = columns.map((c) => track(c.width)).join(' ')
  const minWidth = columns.reduce((acc, c) => acc + (typeof c.width === 'number' ? c.width : FLEX_MIN_WIDTH), 0)
  const selectedIndex = selectedId != null ? indexById.get(selectedId) : undefined
  const rowDomId = (i: number) => `${uid}-r${i}`

  const style = {
    '--dt-cols': gridTemplate,
    '--dt-row': `${rowHeight}px`,
    '--dt-min-width': `${minWidth}px`,
    ...(height != null ? { height, maxHeight: 'none' } : null),
  } as CSSProperties

  const rowCount = indexById.size
  return (
    <div
      ref={scrollRef}
      role="grid"
      aria-rowcount={rowCount + 1}
      aria-activedescendant={selectedIndex != null ? rowDomId(selectedIndex) : undefined}
      tabIndex={0}
      className={clsx(styles.root, className)}
      style={style}
      onKeyDown={onKeyDown}
      {...aria}
    >
      <div role="row" aria-rowindex={1} className={clsx(styles.row, styles.header)} style={{ height: HEADER_HEIGHT }}>
        {columns.map((col) => {
          const active = sort?.columnId === col.id
          const ariaSort = active ? (sort?.direction === 'asc' ? 'ascending' : 'descending') : undefined
          return (
            <div key={col.id} role="columnheader" aria-sort={ariaSort} className={clsx(styles.cell, styles[col.align ?? 'left'])}>
              {col.sortValue ? (
                <button type="button" tabIndex={-1} className={clsx(styles.sortButton, active && styles.sorted)} onClick={() => onHeaderClick(col)}>
                  <span className={styles.headerText}>{col.header}</span>
                  {active && (sort?.direction === 'asc' ? <ArrowUp aria-hidden /> : <ArrowDown aria-hidden />)}
                </button>
              ) : (
                <span className={styles.headerText}>{col.header}</span>
              )}
            </div>
          )
        })}
      </div>

      {rows.length === 0 ? (
        <div className={styles.empty}>
          {empty ?? <EmptyState size="sm" icon={<SearchX />} title="Sin resultados" description="Ninguna fila coincide con los filtros." />}
        </div>
      ) : (
        <div className={styles.body} style={{ height: virtualizer.getTotalSize() }}>
          {virtualizer.getVirtualItems().map((v) => {
            const it = items[v.index]
            const offset = { transform: `translateY(${v.start - HEADER_HEIGHT}px)`, height: v.size }
            if (it.kind === 'group') {
              const isCollapsed = collapsed.has(it.key)
              return (
                <div key={v.key} role="row" className={styles.group} style={offset}>
                  <div role="gridcell" aria-colspan={columns.length} className={styles.groupCell}>
                    <button type="button" tabIndex={-1} className={styles.groupButton} aria-expanded={!isCollapsed} onClick={() => toggleGroup(it.key)}>
                      <ChevronRight aria-hidden className={clsx(styles.chevron, !isCollapsed && styles.open)} />
                      <span className={styles.groupLabel}>{renderGroup ? renderGroup(it.key, it.rows) : it.key}</span>
                      <span className={clsx(styles.groupCount, 'tabular')}>{formatNumber(it.rows.length)}</span>
                    </button>
                  </div>
                </div>
              )
            }
            const id = getRowId(it.row)
            const selected = id === selectedId
            return (
              <div
                key={v.key}
                id={rowDomId(v.index)}
                role="row"
                aria-selected={selected}
                className={clsx(styles.row, styles.dataRow, selected && styles.selected, onOpen && styles.clickable)}
                style={offset}
                onClick={() => {
                  setSelected(id)
                  onOpen?.(it.row)
                }}
              >
                {columns.map((col) => (
                  <div key={col.id} role="gridcell" className={clsx(styles.cell, styles[col.align ?? 'left'])}>
                    {col.cell(it.row)}
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
