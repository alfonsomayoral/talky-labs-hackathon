import { act, render, renderHook } from '@testing-library/react'
import { usePageShortcutGroups, usePageShortcuts, type ShortcutHelp } from './keyboard'

function Page({ title, shortcuts }: { title: string; shortcuts: ShortcutHelp[] }) {
  usePageShortcuts(title, shortcuts)
  return null
}

const ATTENTION: ShortcutHelp[] = [
  { label: 'Aceptar', keys: ['A'] },
  { label: 'Posponer', keys: ['P'] },
]

describe('usePageShortcuts', () => {
  it('lists a page group while the page is mounted', () => {
    const groups = renderHook(() => usePageShortcutGroups())
    const page = render(<Page title="Atención" shortcuts={ATTENTION} />)
    expect(groups.result.current).toEqual([{ title: 'Atención', shortcuts: ATTENTION }])

    act(() => page.unmount())
    expect(groups.result.current).toEqual([])
  })

  it('keeps one entry across re-renders with equal shortcuts', () => {
    const groups = renderHook(() => usePageShortcutGroups())
    const page = render(<Page title="Atención" shortcuts={ATTENTION} />)
    page.rerender(<Page title="Atención" shortcuts={[...ATTENTION]} />)
    expect(groups.result.current).toHaveLength(1)
    page.unmount()
  })
})
