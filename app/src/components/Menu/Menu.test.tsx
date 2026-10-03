import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Menu } from './Menu'

function setup() {
  const onPost = vi.fn()
  render(
    <Menu
      aria-label="Acciones"
      items={[
        { type: 'label', id: 'l', label: 'Dataset' },
        { id: 'post', label: 'Contabilizar', onSelect: onPost },
        { id: 'hold', label: 'Retener', disabled: true, onSelect: () => {} },
        { id: 'reject', label: 'Rechazar', onSelect: () => {} },
      ]}
      trigger={<button type="button">Acciones</button>}
    />,
  )
  return { onPost, trigger: screen.getByRole('button', { name: 'Acciones' }) }
}

describe('Menu', () => {
  it('opens on click and focuses the first enabled item', async () => {
    const { trigger } = setup()
    await userEvent.click(trigger)
    expect(screen.getByRole('menu')).toBeInTheDocument()
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('menuitem', { name: 'Contabilizar' })).toHaveFocus()
  })

  it('skips disabled items with the arrows and wraps around', async () => {
    const { trigger } = setup()
    await userEvent.click(trigger)
    await userEvent.keyboard('{ArrowDown}')
    expect(screen.getByRole('menuitem', { name: 'Rechazar' })).toHaveFocus()
    await userEvent.keyboard('{ArrowDown}')
    expect(screen.getByRole('menuitem', { name: 'Contabilizar' })).toHaveFocus()
  })

  it('runs the item, closes and returns focus to the trigger', async () => {
    const { trigger, onPost } = setup()
    await userEvent.click(trigger)
    await userEvent.keyboard('{Enter}')
    expect(onPost).toHaveBeenCalledOnce()
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('closes with Escape', async () => {
    const { trigger } = setup()
    await userEvent.click(trigger)
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })
})
