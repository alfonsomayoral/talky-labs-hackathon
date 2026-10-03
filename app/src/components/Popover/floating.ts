// Minimal anchored positioning for popovers, menus and tooltips (fixed, flips, clamps to viewport).
import { useCallback, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'

export type Side = 'top' | 'bottom' | 'left' | 'right'
export type Align = 'start' | 'center' | 'end'

const MARGIN = 8

export function computePosition(
  anchor: DOMRect,
  floating: { width: number; height: number },
  side: Side,
  align: Align,
  offset: number,
): { top: number; left: number; side: Side } {
  const vw = window.innerWidth
  const vh = window.innerHeight
  let s = side
  if (s === 'bottom' && anchor.bottom + offset + floating.height > vh - MARGIN && anchor.top - offset - floating.height >= MARGIN) s = 'top'
  else if (s === 'top' && anchor.top - offset - floating.height < MARGIN && anchor.bottom + offset + floating.height <= vh - MARGIN) s = 'bottom'
  else if (s === 'right' && anchor.right + offset + floating.width > vw - MARGIN) s = 'left'
  else if (s === 'left' && anchor.left - offset - floating.width < MARGIN) s = 'right'

  let top: number
  let left: number
  if (s === 'top' || s === 'bottom') {
    top = s === 'bottom' ? anchor.bottom + offset : anchor.top - offset - floating.height
    left =
      align === 'start'
        ? anchor.left
        : align === 'end'
          ? anchor.right - floating.width
          : anchor.left + anchor.width / 2 - floating.width / 2
  } else {
    left = s === 'right' ? anchor.right + offset : anchor.left - offset - floating.width
    top =
      align === 'start'
        ? anchor.top
        : align === 'end'
          ? anchor.bottom - floating.height
          : anchor.top + anchor.height / 2 - floating.height / 2
  }
  left = Math.min(Math.max(left, MARGIN), Math.max(MARGIN, vw - MARGIN - floating.width))
  top = Math.min(Math.max(top, MARGIN), Math.max(MARGIN, vh - MARGIN - floating.height))
  return { top, left, side: s }
}

// Until measured the element is transparent, not `visibility: hidden`, so it can already take focus.
const UNPLACED: CSSProperties = { position: 'fixed', top: 0, left: 0, opacity: 0 }

/** Positions a fixed floating element next to `anchor` while `open`; re-measures on scroll/resize. */
export function useFloating(
  anchor: HTMLElement | null,
  open: boolean,
  { side = 'bottom', align = 'start', offset = 6 }: { side?: Side; align?: Align; offset?: number } = {},
) {
  const floatingRef = useRef<HTMLElement | null>(null)
  const [style, setStyle] = useState<CSSProperties>(UNPLACED)
  const setFloating = useCallback((el: HTMLElement | null) => {
    floatingRef.current = el
  }, [])

  useLayoutEffect(() => {
    const el = floatingRef.current
    if (!open || !anchor || !el) {
      setStyle(UNPLACED)
      return
    }
    const update = () => {
      const pos = computePosition(anchor.getBoundingClientRect(), el.getBoundingClientRect(), side, align, offset)
      setStyle({ position: 'fixed', top: pos.top, left: pos.left })
    }
    update()
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(update) : null
    observer?.observe(el)
    return () => {
      window.removeEventListener('resize', update)
      window.removeEventListener('scroll', update, true)
      observer?.disconnect()
    }
  }, [open, anchor, side, align, offset])

  return { setFloating, style }
}
