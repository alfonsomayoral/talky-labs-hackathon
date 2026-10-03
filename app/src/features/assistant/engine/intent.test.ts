import { detectIntent } from './intent'
import { PRESET_QUESTIONS } from './local'

describe('detectIntent', () => {
  it('maps the four preset questions to their intents', () => {
    expect(PRESET_QUESTIONS.map((q) => detectIntent(q))).toEqual([
      { kind: 'summary' },
      { kind: 'review' },
      { kind: 'balance' },
      { kind: 'process', task: 'ap' },
    ])
  })

  it.each([
    ['Explica API004128', 'API004128'],
    ['¿por qué api004128?', 'api004128'],
    ['Explica ap:API004128', 'ap:API004128'],
    ['¿Y BIN-1100/BL0000706?', 'BIN-1100/BL0000706'],
    ['¿Qué pasó con BL0000085?', 'BL0000085'],
  ])('«%s» explains the item %s', (q, token) => {
    expect(detectIntent(q)).toEqual({ kind: 'explain', token })
  })

  it('a bank account id asks for its status', () => {
    expect(detectIntent('¿Cómo está la cuenta bin-1100?')).toEqual({ kind: 'bank', account: 'BIN-1100' })
    expect(detectIntent('¿Cómo van los bancos?')).toEqual({ kind: 'bank', account: null })
  })

  it('recognises cost, other processes and unknown questions', () => {
    expect(detectIntent('¿Cuánto ha costado la ejecución?')).toEqual({ kind: 'cost' })
    expect(detectIntent('¿Cómo ha decidido los cobros?')).toEqual({ kind: 'process', task: 'ar_cash' })
    expect(detectIntent('Explícame el proceso de intragrupo')).toEqual({ kind: 'process', task: 'ic' })
    expect(detectIntent('¿Cómo ha resuelto la conciliación bancaria?')).toEqual({ kind: 'process', task: 'bank_rec' })
    expect(detectIntent('¿Qué tiempo hace?')).toEqual({ kind: 'unknown' })
  })

  it('company codes, accounts and policy articles are not item ids', () => {
    expect(detectIntent('¿Cuadra el balance de 3100 en la 55500000?')).toEqual({ kind: 'balance' })
    expect(detectIntent('¿Qué tengo que revisar del §2.2.3?')).toEqual({ kind: 'review' })
  })
})
