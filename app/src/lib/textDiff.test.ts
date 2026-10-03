import { describe, expect, it } from 'vitest'
import { textDiff } from './textDiff'

describe('textDiff', () => {
  it('isolates the characters a look-alike domain changes', () => {
    expect(textDiff('señalizaci0nesvial.es', 'señalizacionesvial.es')).toEqual({ before: 'señalizaci', changed: '0', after: 'nesvial.es' })
    expect(textDiff('ffiinstalacionesel-es.es', 'ffiinstalacionesel.es')).toEqual({ before: 'ffiinstalacionesel', changed: '-es', after: '.es' })
  })

  it('returns the whole text when nothing is shared, and nothing changed when equal', () => {
    expect(textDiff('ES11', 'PT22').changed).toBe('ES11')
    expect(textDiff('V1', 'V1').changed).toBe('')
  })
})
