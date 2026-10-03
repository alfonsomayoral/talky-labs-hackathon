import { pageTitle, routeCrumbs } from './routeCrumbs'

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

describe('pageTitle', () => {
  it('names the page before the app, without the section', () => {
    expect(pageTitle('/')).toBe('Resumen · Kalmora Close')
    expect(pageTitle('/tareas/ap')).toBe('Bandeja AP · Kalmora Close')
    expect(pageTitle('/dev/ui')).toBe('Galería de componentes · Kalmora Close')
  })

  it('puts the most specific segment first', () => {
    expect(pageTitle('/tareas/bancos/BIN-1200')).toBe('BIN-1200 · Bancos · Kalmora Close')
  })

  it('says when the page does not exist', () => {
    expect(pageTitle('/balanceX')).toBe('Página no encontrada · Kalmora Close')
  })
})
