import { useId, useState } from 'react'
import { ArrowDownWideNarrow, ArrowUpNarrowWide, ChevronDown, SlidersHorizontal } from 'lucide-react'
import { Button } from '../Button/Button'
import { IconButton } from '../IconButton/IconButton'
import { Popover } from '../Popover/Popover'
import type { SortState } from '../DataTable/model'
import styles from './ViewOptions.module.css'

export interface ViewChoice {
  value: string
  label: string
}

export interface ViewOptionsProps {
  /** Grouping choices; `null` value = no grouping. */
  groupBy?: { options: ViewChoice[]; value: string | null; onChange: (value: string | null) => void }
  /** Sort choices keyed by DataTable column id, so header clicks and this menu stay in sync. */
  sort?: { options: ViewChoice[]; value: SortState | null; onChange: (value: SortState | null) => void }
}

const NONE = '__none__'

/** «Vista» button: group-by and sort for a list (Linear's display options). */
export function ViewOptions({ groupBy, sort }: ViewOptionsProps) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const [open, setOpen] = useState(false)
  const groupId = useId()
  const sortId = useId()

  return (
    <>
      <Button
        size="sm"
        leadingIcon={<SlidersHorizontal />}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={(e) => {
          setAnchor(e.currentTarget)
          setOpen((o) => !o)
        }}
      >
        Vista
      </Button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} align="end" role="dialog" aria-label="Opciones de vista" className={styles.popover}>
        {groupBy && (
          <div className={styles.row}>
            <label htmlFor={groupId} className={styles.label}>
              Agrupar
            </label>
            <span className={styles.selectWrap}>
              <select
                id={groupId}
                className={styles.select}
                value={groupBy.value ?? NONE}
                onChange={(e) => groupBy.onChange(e.target.value === NONE ? null : e.target.value)}
              >
                <option value={NONE}>Sin agrupar</option>
                {groupBy.options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <ChevronDown aria-hidden className={styles.chevron} />
            </span>
          </div>
        )}
        {sort && (
          <div className={styles.row}>
            <label htmlFor={sortId} className={styles.label}>
              Ordenar
            </label>
            <span className={styles.selectWrap}>
              <select
                id={sortId}
                className={styles.select}
                value={sort.value?.columnId ?? NONE}
                onChange={(e) =>
                  sort.onChange(e.target.value === NONE ? null : { columnId: e.target.value, direction: sort.value?.direction ?? 'desc' })
                }
              >
                <option value={NONE}>Orden original</option>
                {sort.options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <ChevronDown aria-hidden className={styles.chevron} />
            </span>
            <IconButton
              size="sm"
              variant="secondary"
              disabled={!sort.value}
              label={sort.value?.direction === 'asc' ? 'Ascendente' : 'Descendente'}
              icon={sort.value?.direction === 'asc' ? <ArrowUpNarrowWide /> : <ArrowDownWideNarrow />}
              onClick={() =>
                sort.value && sort.onChange({ ...sort.value, direction: sort.value.direction === 'asc' ? 'desc' : 'asc' })
              }
            />
          </div>
        )}
      </Popover>
    </>
  )
}
