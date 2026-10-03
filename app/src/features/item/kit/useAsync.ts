import { useEffect, useState, type DependencyList } from 'react'

export type AsyncState<T> = { status: 'loading'; data: null; error: null } | { status: 'ready'; data: T; error: null } | { status: 'error'; data: null; error: string }

/** Runs `load` when `deps` change; ignores results that arrive after a newer load or unmount. */
export function useAsync<T>(load: () => Promise<T>, deps: DependencyList): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: 'loading', data: null, error: null })
  useEffect(() => {
    let alive = true
    setState({ status: 'loading', data: null, error: null })
    load().then(
      (data) => alive && setState({ status: 'ready', data, error: null }),
      (e: unknown) => alive && setState({ status: 'error', data: null, error: e instanceof Error ? e.message : String(e) }),
    )
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}
