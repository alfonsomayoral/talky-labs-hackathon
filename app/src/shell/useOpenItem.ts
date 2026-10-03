// The item peek lives in the URL (`?item=<task>:<key>`) so it works over any route and can be shared.
import { useCallback } from 'react'
import { useSearchParams } from 'react-router'

export const ITEM_PARAM = 'item'

/** Returns `openItem(itemId)`: sets `?item=` on the current URL, keeping the other params. */
export function useOpenItem(): (itemId: string) => void {
  const [searchParams, setSearchParams] = useSearchParams()
  const alreadyOpen = searchParams.has(ITEM_PARAM)
  return useCallback(
    (itemId: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          next.set(ITEM_PARAM, itemId)
          return next
        },
        // Switching items (j/k with the panel open) must not pile up history entries.
        { replace: alreadyOpen, preventScrollReset: true },
      )
    },
    [setSearchParams, alreadyOpen],
  )
}

/** Id of the item open in the peek panel, or null. Lists use it to highlight the open row. */
export function useActiveItemId(): string | null {
  const [searchParams] = useSearchParams()
  return searchParams.get(ITEM_PARAM)
}

/** Removes `?item=` (closes the peek). */
export function useCloseItem(): () => void {
  const [, setSearchParams] = useSearchParams()
  return useCallback(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.delete(ITEM_PARAM)
        return next
      },
      { preventScrollReset: true },
    )
  }, [setSearchParams])
}
