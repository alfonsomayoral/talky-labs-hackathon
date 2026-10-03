import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from 'lucide-react'
import styles from './Toaster.module.css'

export type ToastTone = 'neutral' | 'ok' | 'warn' | 'danger'

export interface ToastOptions {
  description?: ReactNode
  tone?: ToastTone
  action?: { label: string; onClick: () => void }
  /** ms before it disappears; `Infinity` keeps it until dismissed. Default 4000 (6000 for errors). */
  duration?: number
}

interface ToastRecord extends ToastOptions {
  id: number
  title: ReactNode
}

const MAX_VISIBLE = 4
let toasts: ToastRecord[] = []
let nextId = 1
const listeners = new Set<() => void>()

function emit() {
  for (const l of listeners) l()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Shows a transient message. Returns its id (for `toast.dismiss`). Needs `<Toaster />` mounted once. */
export function toast(title: ReactNode, opts: ToastOptions = {}): number {
  const id = nextId++
  toasts = [...toasts, { id, title, ...opts }].slice(-MAX_VISIBLE)
  emit()
  return id
}

toast.success = (title: ReactNode, opts: Omit<ToastOptions, 'tone'> = {}) => toast(title, { ...opts, tone: 'ok' })
toast.error = (title: ReactNode, opts: Omit<ToastOptions, 'tone'> = {}) => toast(title, { ...opts, tone: 'danger' })
toast.dismiss = (id: number) => {
  toasts = toasts.filter((t) => t.id !== id)
  emit()
}

const ICONS: Record<ToastTone, ReactNode> = {
  neutral: <Info aria-hidden />,
  ok: <CircleCheck aria-hidden />,
  warn: <TriangleAlert aria-hidden />,
  danger: <CircleAlert aria-hidden />,
}

function ToastItem({ t }: { t: ToastRecord }) {
  const tone = t.tone ?? 'neutral'
  const duration = t.duration ?? (tone === 'danger' ? 6000 : 4000)
  const [paused, setPaused] = useState(false)

  useEffect(() => {
    if (paused || !Number.isFinite(duration)) return
    const timer = setTimeout(() => toast.dismiss(t.id), duration)
    return () => clearTimeout(timer)
  }, [paused, duration, t.id])

  return (
    <li
      className={styles.toast}
      data-tone={tone}
      role={tone === 'danger' ? 'alert' : 'status'}
      onPointerEnter={() => setPaused(true)}
      onPointerLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <span className={styles.icon}>{ICONS[tone]}</span>
      <div className={styles.content}>
        <p className={styles.title}>{t.title}</p>
        {t.description != null && <p className={styles.description}>{t.description}</p>}
      </div>
      {t.action && (
        <button
          type="button"
          className={styles.action}
          onClick={() => {
            t.action?.onClick()
            toast.dismiss(t.id)
          }}
        >
          {t.action.label}
        </button>
      )}
      <button type="button" className={styles.close} aria-label="Cerrar aviso" onClick={() => toast.dismiss(t.id)}>
        <X aria-hidden />
      </button>
    </li>
  )
}

/** Mount once at the root (main.tsx does). */
export function Toaster() {
  const items = useSyncExternalStore(subscribe, () => toasts, () => toasts)
  return createPortal(
    <ol className={styles.region} aria-label="Avisos">
      {items.map((t) => (
        <ToastItem key={t.id} t={t} />
      ))}
    </ol>,
    document.body,
  )
}
