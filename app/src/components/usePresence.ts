import { useEffect, useState } from 'react'

/** How long an overlay stays mounted after it closes; a little over `--duration-fast`, its exit animation. */
export const EXIT_MS = 140

/**
 * Keeps an overlay mounted while its exit animation plays. `mounted` drives rendering; `closing` is true
 * from the moment `open` turns false until the overlay unmounts.
 */
export function usePresence(open: boolean): { mounted: boolean; closing: boolean } {
  const [mounted, setMounted] = useState(open)
  if (open && !mounted) setMounted(true)

  useEffect(() => {
    if (open || !mounted) return
    const timer = setTimeout(() => setMounted(false), EXIT_MS)
    return () => clearTimeout(timer)
  }, [open, mounted])

  return { mounted: open || mounted, closing: !open && mounted }
}
