// Keyboard plumbing shared by the shell and the components.
//
// Layers: every overlay (dialog, menu, popover, side panel) registers itself while open.
// Esc closes only the topmost layer, and single-key hotkeys (j/k, g+letter, ?) are
// suspended while a modal layer (dialog, menu, popover) is open.
import { useEffect, useRef, type KeyboardEvent as ReactKeyboardEvent } from 'react'

export const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
/** Label for the platform modifier: ⌘ on macOS, Ctrl elsewhere. */
export const MOD_KEY = IS_MAC ? '⌘' : 'Ctrl'

interface Layer {
  modal: boolean
  onEscape: () => void
}

const layers: Layer[] = []
let escapeListening = false

function handleEscape(e: KeyboardEvent) {
  if (e.key !== 'Escape' || e.defaultPrevented || layers.length === 0) return
  e.preventDefault()
  layers[layers.length - 1].onEscape()
}

function pushLayer(layer: Layer): () => void {
  if (!escapeListening && typeof window !== 'undefined') {
    window.addEventListener('keydown', handleEscape)
    escapeListening = true
  }
  layers.push(layer)
  return () => {
    const i = layers.lastIndexOf(layer)
    if (i >= 0) layers.splice(i, 1)
  }
}

export function hasModalLayer(): boolean {
  return layers.some((l) => l.modal)
}

/** Registers an overlay while `active`; Esc calls `onEscape` when it is the topmost one. */
export function useLayer(active: boolean, onEscape: () => void, opts: { modal?: boolean } = {}) {
  const onEscapeRef = useRef(onEscape)
  useEffect(() => {
    onEscapeRef.current = onEscape
  })
  const modal = opts.modal ?? true
  useEffect(() => {
    if (!active) return
    return pushLayer({ modal, onEscape: () => onEscapeRef.current() })
  }, [active, modal])
}

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (tag !== 'INPUT') return false
  const type = (target as HTMLInputElement).type
  return !['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file'].includes(type)
}

/** True when a single-key hotkey must not fire: typing, a modifier held, or a modal layer open. */
export function shouldIgnoreHotkey(e: KeyboardEvent): boolean {
  return e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || isTypingTarget(e.target) || hasModalLayer()
}

const SEQUENCE_TIMEOUT_MS = 1200

export interface GlobalShortcutHandlers {
  /** ⌘K / Ctrl+K — works everywhere, also while typing. */
  onPalette: () => void
  /** `?` */
  onHelp: () => void
  /** `g` then a letter; receives the letter. Returns true when it was handled. */
  onGo: (letter: string) => boolean
}

/** Installs the app-wide shortcuts. Mount once (the shell does). */
export function useGlobalShortcuts(handlers: GlobalShortcutHandlers) {
  const ref = useRef(handlers)
  useEffect(() => {
    ref.current = handlers
  })

  useEffect(() => {
    let pendingG = false
    let timer: ReturnType<typeof setTimeout> | undefined

    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        ref.current.onPalette()
        return
      }
      if (shouldIgnoreHotkey(e)) {
        pendingG = false
        return
      }
      if (pendingG) {
        pendingG = false
        clearTimeout(timer)
        if (ref.current.onGo(e.key.toLowerCase())) e.preventDefault()
        return
      }
      if (e.key === '?' || (e.key === '/' && e.shiftKey)) {
        e.preventDefault()
        ref.current.onHelp()
      } else if (e.key === 'g' && !e.shiftKey) {
        pendingG = true
        clearTimeout(timer)
        timer = setTimeout(() => (pendingG = false), SEQUENCE_TIMEOUT_MS)
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      clearTimeout(timer)
    }
  }, [])
}

/** Keeps Tab / Shift+Tab inside `container` (for dialogs and the side panel). */
export function trapTabKey(e: KeyboardEvent | ReactKeyboardEvent, container: HTMLElement | null) {
  if (e.key !== 'Tab' || !container) return
  const focusables = getFocusable(container)
  if (focusables.length === 0) {
    e.preventDefault()
    container.focus()
    return
  }
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  const active = document.activeElement
  if (e.shiftKey && (active === first || active === container)) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && active === last) {
    e.preventDefault()
    first.focus()
  }
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function getFocusable(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => !el.closest('[inert], [hidden]'))
}
