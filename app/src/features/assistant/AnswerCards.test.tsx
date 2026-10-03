import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router'
import { AnswerCards, Citations } from './AnswerCards'
import type { AssistantCard } from './engine'

function Location() {
  return <output data-testid="location">{useLocation().search}</output>
}

function renderInRouter(ui: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={['/asistente']}>
      {ui}
      <Location />
    </MemoryRouter>,
  )
}

const opened = () => new URLSearchParams(screen.getByTestId('location').textContent ?? '').get('item')

describe('assistant answers open the cited items in the side panel', () => {
  it('a cited item sets ?item= and policy articles are shown as text', async () => {
    renderInRouter(<Citations citations={[{ item: 'ap:API004128' }, { policy_ref: '§2.2.3' }, { item: 'ap:API004128' }]} />)
    expect(screen.getAllByRole('button')).toHaveLength(1)
    expect(screen.getByText('§2.2.3')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'API004128' }))
    expect(opened()).toBe('ap:API004128')
  })

  it('every row of an items card and the reasoning card open their item', async () => {
    const cards: AssistantCard[] = [
      { type: 'items', title: 'Te necesitan', items: [{ item: 'bank_rec:BIN-1100/BL0000706', title: 'Cobro sin registrar', amount: 51496121, currency: 'EUR', priority: 'P1' }], total: 3 },
      { type: 'reasoning', item: 'ap:API004128', headline: 'Supera las 14 comprobaciones de la §2.2 y se contabiliza.', facts: [{ label: 'Proveedor', mono: 'V100009' }], steps: [] },
      { type: 'metric', metrics: [{ label: 'Importe pendiente', value: { kind: 'money', cents: 116348001, currency: 'EUR' } }] },
    ]
    renderInRouter(<AnswerCards cards={cards} />)
    expect(screen.getByText('1 de 3')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Cobro sin registrar/ }))
    expect(opened()).toBe('bank_rec:BIN-1100/BL0000706')
    await userEvent.click(screen.getByRole('button', { name: /Abrir partida/ }))
    expect(opened()).toBe('ap:API004128')
    expect(screen.getByText('Supera las 14 comprobaciones de la §2.2 y se contabiliza.')).toBeInTheDocument()
  })
})
