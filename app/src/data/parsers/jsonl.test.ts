// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { JsonlError, parseJsonlBlob, parseJsonlText, streamJsonl } from './jsonl'

describe('JSONL', () => {
  it('parses text with CRLF and blank lines', () => {
    expect(parseJsonlText('{"a":1}\r\n\r\n{"a":2}\n  \n{"a":3}')).toEqual([{ a: 1 }, { a: 2 }, { a: 3 }])
  })

  it('streams across chunk boundaries, including split multi-byte characters', async () => {
    const text = '{"t":"cañón – 1"}\r\n\n{"t":"Câmara"}\n{"t":"último"}'
    const bytes = new TextEncoder().encode(text)
    const parts = [bytes.slice(0, 7), bytes.slice(7, 9), bytes.slice(9, 22), bytes.slice(22, 23), bytes.slice(23)]
    const rows: { t: string }[] = []
    const count = await streamJsonl<{ t: string }>(new Blob(parts), (r) => rows.push(r))
    expect(count).toBe(3)
    expect(rows.map((r) => r.t)).toEqual(['cañón – 1', 'Câmara', 'último'])
  })

  it('handles a final line without newline and an empty blob', async () => {
    expect(await parseJsonlBlob(new Blob(['{"x":1}\n{"x":2}']))).toEqual([{ x: 1 }, { x: 2 }])
    expect(await parseJsonlBlob(new Blob([]))).toEqual([])
  })

  it('reports the line of invalid JSON', async () => {
    await expect(parseJsonlBlob(new Blob(['{"x":1}\n\n{oops}\n']))).rejects.toThrow(JsonlError)
    expect(() => parseJsonlText('{"x":1}\n{oops')).toThrow(/línea 2/)
  })
})
