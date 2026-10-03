import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import clsx from 'clsx'
import { X } from 'lucide-react'
import { trapTabKey, useLayer } from '@/lib/keyboard'
import { IconButton } from '../IconButton/IconButton'
import { usePresence } from '../usePresence'
import styles from './SidePanel.module.css'

export interface SidePanelProps {
  open: boolean
  onClose: () => void
  title?: ReactNode
  /** Header buttons before the close button. */
  actions?: ReactNode
  footer?: ReactNode
  /** Initial width in px. Default 560. */
  defaultWidth?: number
  minWidth?: number
  /** Remembers the dragged width in localStorage under this key. */
  storageKey?: string
  'aria-label'?: string
  className?: string
  children: ReactNode
}

const MAX_RATIO = 0.8

function readWidth(key: string | undefined, fallback: number): number {
  if (!key) return fallback
  try {
    const n = Number(localStorage.getItem(key))
    return Number.isFinite(n) && n > 0 ? n : fallback
  } catch {
    return fallback
  }
}

/**
 * Right "peek" panel over the page (non-modal: the list behind stays usable and j/k keep working).
 * Esc closes it, Tab cycles inside it, the left edge resizes it.
 */
export function SidePanel({
  open,
  onClose,
  title,
  actions,
  footer,
  defaultWidth = 560,
  minWidth = 400,
  storageKey,
  className,
  children,
  ...aria
}: SidePanelProps) {
  const presence = usePresence(open)
  const [width, setWidth] = useState(() => readWidth(storageKey, defaultWidth))
  const [resizing, setResizing] = useState(false)
  const panelRef = useRef<HTMLElement>(null)

  useLayer(open, onClose, { modal: false })

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const panel = panelRef.current
    panel?.focus({ preventScroll: true })
    return () => {
      // Give focus back only if it was inside the panel (now removed) — never steal it from where the user clicked.
      const active = document.activeElement
      const lost = !active || active === document.body || panel?.contains(active)
      if (lost && previous?.isConnected) previous.focus({ preventScroll: true })
    }
  }, [open])

  const clamp = (w: number) => Math.round(Math.min(Math.max(w, minWidth), window.innerWidth * MAX_RATIO))

  const persist = (w: number) => {
    if (!storageKey) return
    try {
      localStorage.setItem(storageKey, String(w))
    } catch {
      /* storage unavailable: keep the width for this session only */
    }
  }

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    setResizing(true)
  }
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (resizing) setWidth(clamp(window.innerWidth - e.clientX))
  }
  const onPointerUp = () => {
    if (!resizing) return
    setResizing(false)
    persist(width)
  }
  const onHandleKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const delta = e.key === 'ArrowLeft' ? 32 : e.key === 'ArrowRight' ? -32 : 0
    if (!delta) return
    e.preventDefault()
    const next = clamp(width + delta)
    setWidth(next)
    persist(next)
  }

  if (!presence.mounted) return null
  const shown = Math.min(width, Math.round(window.innerWidth * MAX_RATIO))
  return createPortal(
    <aside
      ref={panelRef}
      role="complementary"
      tabIndex={-1}
      className={clsx(styles.panel, resizing && styles.resizing, presence.closing && styles.closing, className)}
      inert={presence.closing}
      aria-hidden={presence.closing || undefined}
      style={{ width: shown }}
      onKeyDown={(e) => trapTabKey(e, panelRef.current)}
      {...aria}
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Cambiar ancho del panel"
        aria-valuenow={shown}
        aria-valuemin={minWidth}
        aria-valuemax={Math.round(window.innerWidth * MAX_RATIO)}
        tabIndex={0}
        className={styles.handle}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={onHandleKey}
      />
      <header className={styles.header}>
        <div className={styles.title}>{title}</div>
        <div className={styles.actions}>
          {actions}
          <IconButton icon={<X />} label="Cerrar panel" shortcut={['Esc']} size="sm" onClick={onClose} tooltipSide="bottom" />
        </div>
      </header>
      <div className={styles.body}>{children}</div>
      {footer != null && <footer className={styles.footer}>{footer}</footer>}
    </aside>,
    document.body,
  )
}
