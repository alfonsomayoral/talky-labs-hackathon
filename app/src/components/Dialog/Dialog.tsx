import { useEffect, useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import clsx from 'clsx'
import { X } from 'lucide-react'
import { getFocusable, trapTabKey, useLayer } from '@/lib/keyboard'
import { IconButton } from '../IconButton/IconButton'
import { usePresence } from '../usePresence'
import styles from './Dialog.module.css'

export interface DialogProps {
  open: boolean
  onClose: () => void
  /** Visible heading; with `bare` it only labels the dialog for assistive tech. */
  title: ReactNode
  description?: ReactNode
  /** Right-aligned buttons; put the primary one last. */
  footer?: ReactNode
  /** 400 / 560 / 720 px. Default `md`. */
  size?: 'sm' | 'md' | 'lg'
  /** No header, padding or footer chrome (command palette and custom layouts). */
  bare?: boolean
  /** `top` sits at 14vh (palettes); `center` for confirmations and forms. */
  placement?: 'center' | 'top'
  className?: string
  children?: ReactNode
}

const FIELD = 'input:not([type="hidden"]), select, textarea, [contenteditable="true"]'

/** First field, else the first control that is not the header's close button, else the panel. */
function initialFocus(panel: HTMLElement): HTMLElement {
  const focusable = getFocusable(panel)
  return focusable.find((el) => el.matches(FIELD)) ?? focusable.find((el) => !el.hasAttribute('data-dialog-close')) ?? panel
}

/** Modal dialog: overlay, focus trap, Esc and overlay click close, focus returns to the opener. */
export function Dialog({ open, onClose, title, description, footer, size = 'md', bare, placement = 'center', className, children }: DialogProps) {
  const presence = usePresence(open)
  const titleId = useId()
  const descriptionId = useId()
  const panelRef = useRef<HTMLDivElement>(null)

  useLayer(open, onClose)

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const panel = panelRef.current
    // An `autoFocus` child is already focused by React; keep it.
    if (panel && !panel.contains(document.activeElement)) initialFocus(panel).focus({ preventScroll: true })
    return () => {
      if (previous?.isConnected) previous.focus({ preventScroll: true })
    }
  }, [open])

  if (!presence.mounted) return null
  return createPortal(
    <div
      className={clsx(styles.overlay, placement === 'top' && styles.top, presence.closing && styles.closing)}
      inert={presence.closing}
      aria-hidden={presence.closing || undefined} onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={bare ? undefined : titleId}
        aria-label={bare && typeof title === 'string' ? title : undefined}
        aria-describedby={description != null && !bare ? descriptionId : undefined}
        tabIndex={-1}
        className={clsx(styles.panel, styles[size], bare && styles.bare, className)}
        onKeyDown={(e) => trapTabKey(e, panelRef.current)}
      >
        {bare ? (
          children
        ) : (
          <>
            <header className={styles.header}>
              <div className={styles.heading}>
                <h2 id={titleId} className={styles.title}>
                  {title}
                </h2>
                {description != null && (
                  <p id={descriptionId} className={styles.description}>
                    {description}
                  </p>
                )}
              </div>
              <IconButton icon={<X />} label="Cerrar" size="sm" onClick={onClose} tooltip={false} data-dialog-close="" />
            </header>
            {children != null && <div className={styles.body}>{children}</div>}
            {footer != null && <footer className={styles.footer}>{footer}</footer>}
          </>
        )}
      </div>
    </div>,
    document.body,
  )
}
