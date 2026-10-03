import { useId, useMemo, useState, type KeyboardEvent, type ReactNode } from 'react'
import clsx from 'clsx'
import { Check, ChevronDown, Plus, X } from 'lucide-react'
import { formatNumber } from '@/lib/format'
import { Button } from '../Button/Button'
import { Popover } from '../Popover/Popover'
import styles from './FilterBar.module.css'

export interface FilterBarProps {
  children: ReactNode
  /** Shows «Limpiar» when set (pass it only while some filter is active). */
  onClear?: () => void
  /** Right side: result count, ViewOptions. */
  end?: ReactNode
  className?: string
}

/** Row of FilterChips. */
export function FilterBar({ children, onClear, end, className }: FilterBarProps) {
  return (
    <div className={clsx(styles.bar, className)} role="toolbar" aria-label="Filtros">
      <div className={styles.chips}>
        {children}
        {onClear && (
          <Button variant="ghost" size="sm" onClick={onClear}>
            Limpiar
          </Button>
        )}
      </div>
      {end != null && <div className={styles.end}>{end}</div>}
    </div>
  )
}

export interface FilterOption {
  value: string
  label: string
  count?: number
  icon?: ReactNode
}

export interface FilterChipProps {
  /** Facet name: «Estado», «Sociedad», «Motivo». */
  label: string
  icon?: ReactNode
  options: FilterOption[]
  selected: string[]
  onChange: (next: string[]) => void
  /** Search box in the dropdown. Default: when there are more than 7 options. */
  searchable?: boolean
}

const normalize = (s: string) =>
  s
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()

/** Multi-select facet: dashed «+ Estado» when empty, «Estado: Resuelto +1» when active. */
export function FilterChip({ label, icon, options, selected, onChange, searchable }: FilterChipProps) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const listId = useId()
  const withSearch = searchable ?? options.length > 7

  const visible = useMemo(() => {
    const q = normalize(query.trim())
    return q ? options.filter((o) => normalize(o.label).includes(q) || normalize(o.value).includes(q)) : options
  }, [options, query])

  const selectedSet = new Set(selected)
  const toggle = (value: string) => onChange(selectedSet.has(value) ? selected.filter((v) => v !== value) : [...selected, value])

  const close = () => {
    setOpen(false)
    setQuery('')
  }

  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const delta = e.key === 'ArrowDown' ? 1 : -1
      setActive((i) => (visible.length ? (i + delta + visible.length) % visible.length : 0))
    } else if (e.key === 'Enter' || (e.key === ' ' && !withSearch)) {
      e.preventDefault()
      const option = visible[active]
      if (option) toggle(option.value)
    }
  }

  const summary = (() => {
    if (selected.length === 0) return null
    const first = options.find((o) => o.value === selected[0])?.label ?? selected[0]
    return selected.length === 1 ? first : `${first} +${selected.length - 1}`
  })()

  const activeId = visible[active] ? `${listId}-${active}` : undefined

  return (
    <span className={clsx(styles.chip, summary && styles.activeChip)}>
      <button
        type="button"
        className={styles.trigger}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={(e) => {
          setAnchor(e.currentTarget)
          setActive(0)
          setOpen((o) => !o)
        }}
      >
        {summary ? icon : <Plus aria-hidden />}
        <span className={styles.facet}>{label}</span>
        {summary && <span className={styles.value}>{summary}</span>}
        {summary && <ChevronDown aria-hidden className={styles.chevron} />}
      </button>
      {summary && (
        <button type="button" className={styles.clear} aria-label={`Quitar filtro ${label}`} onClick={() => onChange([])}>
          <X aria-hidden />
        </button>
      )}

      <Popover open={open} onClose={close} anchor={anchor} className={styles.popover} aria-label={label}>
        {withSearch && (
          <input
            className={styles.search}
            placeholder={`Filtrar ${label.toLowerCase()}…`}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setActive(0)
            }}
            onKeyDown={onKeyDown}
            role="combobox"
            aria-expanded
            aria-controls={listId}
            aria-activedescendant={activeId}
            aria-label={`Buscar en ${label}`}
          />
        )}
        <div
          id={listId}
          role="listbox"
          aria-multiselectable
          aria-label={label}
          tabIndex={withSearch ? -1 : 0}
          aria-activedescendant={withSearch ? undefined : activeId}
          className={styles.list}
          onKeyDown={withSearch ? undefined : onKeyDown}
        >
          {visible.length === 0 && <div className={styles.noResults}>Sin coincidencias</div>}
          {visible.map((o, i) => {
            const isSelected = selectedSet.has(o.value)
            return (
              <div
                key={o.value}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={isSelected}
                className={clsx(styles.option, i === active && styles.optionActive)}
                onPointerMove={() => setActive(i)}
                onClick={() => toggle(o.value)}
              >
                <span className={clsx(styles.checkbox, isSelected && styles.checked)} aria-hidden>
                  {isSelected && <Check />}
                </span>
                {o.icon}
                <span className={styles.optionLabel}>{o.label}</span>
                {o.count != null && <span className={clsx(styles.count, 'tabular')}>{formatNumber(o.count)}</span>}
              </div>
            )
          })}
        </div>
        {selected.length > 0 && (
          <div className={styles.footer}>
            <span className={styles.footerCount}>{selected.length} seleccionados</span>
            <Button variant="ghost" size="sm" onClick={() => onChange([])}>
              Limpiar
            </Button>
          </div>
        )}
      </Popover>
    </span>
  )
}
