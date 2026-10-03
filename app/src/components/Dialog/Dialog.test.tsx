import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Menu } from '../Menu/Menu'
import { Dialog } from './Dialog'

function Harness() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Abrir
      </button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Descartar ejecución" footer={<button type="button">Confirmar</button>}>
        <Menu items={[{ id: 'a', label: 'Opción', onSelect: () => {} }]} trigger={<button type="button">Más</button>} />
      </Dialog>
    </>
  )
}

describe('Dialog', () => {
  it('moves focus inside, traps Tab and returns focus to the opener', async () => {
    render(<Harness />)
    const opener = screen.getByRole('button', { name: 'Abrir' })
    await userEvent.click(opener)
    const dialog = screen.getByRole('dialog', { name: 'Descartar ejecución' })
    expect(dialog).toContainElement(document.activeElement as HTMLElement)

    for (let i = 0; i < 5; i++) await userEvent.tab()
    expect(dialog).toContainElement(document.activeElement as HTMLElement)

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('closes only the topmost layer on Escape', async () => {
    render(<Harness />)
    await userEvent.click(screen.getByRole('button', { name: 'Abrir' }))
    await userEvent.click(screen.getByRole('button', { name: 'Más' }))
    expect(screen.getByRole('menu')).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
