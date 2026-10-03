// @vitest-environment node
import { describe, expect, it } from 'vitest'
import type { BankLine } from '@/domain/types'
import { DEV_PHASE, hasDev, hasTest, nodeFs, readJsonl, TEST_PHASE } from '../testing/nodeData'
import { mapToLines, parseRawStatement, statementFormat } from './bankStatement'
import { parseN43 } from './n43'
import { decimalToCents, decodeText } from './text'

const latin1 = async (path: string) => decodeText(new Uint8Array(await (await nodeFs.openAsBlob(path)).arrayBuffer()))

describe('Norma 43 (synthetic)', () => {
  const rec = (...parts: string[]) => parts.join('').padEnd(80, ' ')
  const file = [
    rec('11', '9101', '2938', '2848142243', '260701', '260731', '2', '00000001000000', '978', '3', 'KALMORA'.padEnd(26), '   '),
    rec('22', '    ', '2938', '260703', '260704', '04', '012', '1', '00000004885000', '3365553690', ''.padEnd(12), 'APORT 07/2026'),
    rec('23', '01', 'TRANSFERENCIA A UTE KALMORA HIDROCON L', 'ORDEN 1'),
    rec('23', '02', 'ORDENANTE X'),
    rec('22', '    ', '2938', '260706', '260706', '02', '011', '2', '00000000012345', '0000000000'),
    rec('24', '01', '840', '00000000240000'),
    rec('33', '9101', '2938', '2848142243', '00001', '00000004885000', '00001', '00000000012345', '1', '00000003872655', '978'),
    rec('88', '9'.repeat(18), '000005'),
  ].join('\r\n')

  it('reads movements, signs, dates and groups 23/24 under their 22', () => {
    const { movements, accounts, warnings } = parseN43(file)
    expect(warnings).toEqual([])
    expect(movements).toHaveLength(2)
    expect(movements[0]).toMatchObject({ amount: -4885000, bookingDate: '2026-07-03', valueDate: '2026-07-04', commonConcept: '04', ownConcept: '012', reference2: 'APORT 07/2026' })
    expect(movements[0].concepts).toEqual(['TRANSFERENCIA A UTE KALMORA HIDROCON L', 'ORDEN 1', 'ORDENANTE X'])
    expect(movements[0].raw).toHaveLength(3)
    expect(movements[1]).toMatchObject({ amount: 12345, fx: { currency: 'USD', amount: 240000 } })
    expect(accounts[0]).toMatchObject({ opening: 1000000, closing: -3872655, currency: 'EUR', debitCount: 1, creditCount: 1 })
  })
})

describe('decimalToCents', () => {
  it('converts without float error', () => {
    expect(decimalToCents('4087.07')).toBe(408707)
    expect(decimalToCents('469994,66')).toBe(46999466)
    expect(decimalToCents('-0.5')).toBe(-50)
    expect(decimalToCents('1,234.56')).toBe(123456)
    expect(decimalToCents('18')).toBe(1800)
  })
})

describe.skipIf(!hasDev)('raw statements vs lines.jsonl (dev)', () => {
  const check = async (account: string, ext: string) => {
    const base = `${DEV_PHASE}/bank/${account}/2026-07`
    const lines = readJsonl<BankLine>(`${base}.lines.jsonl`)
    const raw = parseRawStatement(statementFormat(`${base}.${ext}`)!, await latin1(`${base}.${ext}`))
    expect(raw.movements).toHaveLength(lines.length)
    raw.movements.forEach((m, i) => {
      expect(m.amount).toBe(lines[i].amount)
      expect(m.bookingDate).toBe(lines[i].booking_date)
      if (m.valueDate) expect(m.valueDate).toBe(lines[i].value_date)
    })
    const mapped = mapToLines(raw, lines, `${account} 2026-07`)
    expect(mapped.warnings).toEqual([])
    expect(mapped.details.map((d) => d.bank_line)).toEqual(lines.map((l) => l.bank_line))
    return mapped
  }

  it('N43: BIN-1100', async () => {
    const mapped = await check('BIN-1100', 'n43')
    expect(mapped.opening).not.toBeNull()
    const pooling = mapped.details.find((d) => d.concepts[0]?.startsWith('TRASPASO CASH POOLING'))
    expect(pooling?.raw[0]).toMatch(/^22/)
    expect(mapped.details.some((d) => d.concepts.some((c) => c.includes('DIPUTACIÓN')))).toBe(true)
  })

  it('CAMT.053: BLC-2100 (ids from NtryRef)', async () => {
    const mapped = await check('BLC-2100', 'camt053.xml')
    expect(mapped.details[1].references.EndToEndId).toBe('ORDEN DE PAGO 20')
    expect(mapped.details[1].concepts[0]).toContain('CÂMARA MUNICIPAL')
    expect(mapped.details[0].raw[0]).toMatch(/^<Ntry>[\s\S]*<\/Ntry>$/)
  })

  it('CSV: BANH-3100-MXN and BANH-3100-USD', async () => {
    const mx = await check('BANH-3100-MXN', 'csv')
    expect(mx.details[0].references['Clave de rastreo']).toBe('202607063719685188')
    await check('BANH-3100-USD', 'csv')
  })
})

describe.skipIf(!hasDev || !hasTest)('every statement of both phases maps cleanly', () => {
  it('has no warnings', async () => {
    const warnings: string[] = []
    let statements = 0
    for (const phase of [DEV_PHASE, TEST_PHASE]) {
      for (const rel of nodeFs.readdirSync(`${phase}/bank`, { recursive: true })) {
        const path = `${phase}/bank/${rel}`
        const format = rel.endsWith('.lines.jsonl') ? null : statementFormat(path)
        if (!format) continue
        const linesPath = path.replace(/\.(n43|camt053\.xml|csv)$/, '.lines.jsonl')
        const mapped = mapToLines(parseRawStatement(format, await latin1(path)), readJsonl<BankLine>(linesPath), rel)
        warnings.push(...mapped.warnings)
        statements++
      }
    }
    expect(statements).toBe(96)
    expect(warnings).toEqual([])
  })
})
