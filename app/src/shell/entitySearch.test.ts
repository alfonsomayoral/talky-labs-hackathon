import { buildEntityIndex, journalHit, searchEntities, type SearchItem, type SearchSources } from './entitySearch'

const sources: SearchSources = {
  vendors: [
    { id: 'V100045', name: 'Logística Vegalta, S.L.', tax_id: 'B12345678' },
    { id: 'V100450', name: 'Áridos del Sur', tax_id: 'B87654321' },
  ],
  customers: [{ id: 'C200010', name: 'Ayuntamiento de Getafe', tax_id: 'P2806500A' }],
  chartOfAccounts: [
    { account: '40090000', description: 'Proveedores, facturas pendientes de recibir' },
    { account: '40000000', description: 'Proveedores' },
  ],
  bankStatements: [{ account: 'BIN-1100', month: '2026-07', lines: [{ bank_line: 'BL0000085', text: 'TRANSF CLIENTE' }] }],
}

const items: SearchItem[] = [
  { id: 'ap:API004128', task: 'ap', key: 'API004128', title: 'Factura', company: '1100', evidence: [] },
  { id: 'ar_cash:BL0000085', task: 'ar_cash', key: 'BL0000085', title: 'Cobro', company: '1100', evidence: [] },
  {
    id: 'bank_rec:BIN-1100/match-1',
    task: 'bank_rec',
    key: 'BIN-1100/match-1',
    title: 'Casación',
    company: '1100',
    evidence: [
      { kind: 'bank', account: 'BIN-1100', bank_line: 'BL0000085' },
      { kind: 'journal', book_line: '1100-2026-1400000003#1' },
    ],
  },
]

const index = buildEntityIndex(sources, items)
const ids = (q: string) => searchEntities(index, q).map((h) => h.id)

describe('searchEntities', () => {
  it('finds an item by its document id and opens its panel', () => {
    const [hit] = searchEntities(index, 'api004128')
    expect(hit).toMatchObject({ id: 'ap:API004128', group: 'Partidas', target: { kind: 'item', itemId: 'ap:API004128', task: 'ap' } })
  })

  it('finds every item that references a bank line, plus the statement line', () => {
    expect(ids('BL0000085')).toEqual(['ar_cash:BL0000085', 'bank_rec:BIN-1100/match-1', 'bank:BIN-1100/BL0000085'])
    expect(searchEntities(index, 'BL0000085').at(-1)?.target).toEqual({ kind: 'route', to: '/datos/extractos/BIN-1100/2026-07' })
  })

  it('finds items through the journal entry of their evidence', () => {
    expect(ids('1100-2026-1400000003')).toEqual(['bank_rec:BIN-1100/match-1'])
  })

  it('ranks exact ids before prefixes and substrings', () => {
    expect(ids('V100045')).toEqual(['vendor:V100045'])
    expect(ids('V100')).toEqual(['vendor:V100045', 'vendor:V100450'])
    expect(ids('proveedores')).toEqual(['account:40000000', 'account:40090000'])
    expect(ids('4009')).toEqual(['account:40090000'])
  })

  it('matches names without accents or case and links to the explorer', () => {
    const [hit] = searchEntities(index, 'aridos')
    expect(hit).toMatchObject({ id: 'vendor:V100450', target: { kind: 'route', to: '/datos/proveedores/V100450' } })
    expect(ids('getafe')).toEqual(['customer:C200010'])
    expect(searchEntities(index, '40090000')[0].target).toEqual({ kind: 'route', to: '/datos/cuentas/40090000' })
  })

  it('needs at least two characters', () => {
    expect(searchEntities(index, ' a ')).toEqual([])
  })
})

describe('journalHit', () => {
  it('links a journal entry to the explorer', () => {
    const hit = journalHit({ id: '1100-2024-5000000006', company: '1100', header_text: 'Hoja de entrada', posting_date: '2024-09-30' })
    expect(hit).toMatchObject({ group: 'Asientos', label: '1100-2024-5000000006', target: { kind: 'route', to: '/datos/diario/1100-2024-5000000006' } })
  })
})
