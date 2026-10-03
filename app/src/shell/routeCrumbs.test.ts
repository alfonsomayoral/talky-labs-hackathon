import { routeCrumbs } from './routeCrumbs'

const labels = (path: string) => routeCrumbs(path).map((c) => c.label)

describe('routeCrumbs', () => {
  it('shows only the entry for top-level pages without a section', () => {
    expect(labels('/')).toEqual(['Resumen'])
    expect(labels('/atencion')).toEqual(['Atención'])
  })

  it('prefixes the section title', () => {
    expect(labels('/tareas/ap')).toEqual(['Tareas', 'Bandeja AP'])
  })

  it('adds nested segments with links', () => {
    const crumbs = routeCrumbs('/tareas/bancos/ES1200491500051234567892')
    expect(crumbs.map((c) => c.label)).toEqual(['Tareas', 'Bancos', 'ES1200491500051234567892'])
    expect(crumbs[1].to).toBe('/tareas/bancos')
  })

  it('names known segments and capitalizes plain words', () => {
    expect(labels('/ejecuciones/nueva')).toEqual(['Entrega', 'Ejecuciones', 'Nuevo cierre'])
    expect(labels('/datos/maestros')).toEqual(['Contabilidad', 'Datos', 'Maestros'])
  })

  it('does not confuse prefixes of other entries', () => {
    expect(labels('/comparar')).toEqual(['Entrega', 'Comparar'])
    expect(labels('/balanceX')).toEqual(['Página no encontrada'])
  })

  it('labels dev pages', () => {
    expect(labels('/dev/ui')).toEqual(['Desarrollo', 'Galería de componentes'])
  })
})
