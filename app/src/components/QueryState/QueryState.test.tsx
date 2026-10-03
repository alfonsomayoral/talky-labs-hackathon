import { render, screen } from '@testing-library/react'
import { QueryState } from './QueryState'

describe('QueryState', () => {
  it('announces loading in words', () => {
    render(<QueryState status="loading">listo</QueryState>)
    expect(screen.getByRole('status')).toHaveTextContent('Cargando…')
  })

  it('announces an error as an alert with its message', () => {
    render(
      <QueryState status="error" error="Falta golden/">
        listo
      </QueryState>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('No se pudo cargarFalta golden/')
  })
})
