// @vitest-environment node
import type { AgentEvent, ApRow } from '@/domain/types'
import { deriveRun, itemEntries } from '@/engine'
import { apCascade, bankMatchDetail, loanInterest, reasoningSteps, reasoningSummary } from './reasoning'
import { fixtureCore, fixtureRun } from './testing/fixture'

const nbsp = (s: string) => s.replace(/\u00a0/g, ' ')

const ev = (seq: number, kind: AgentEvent['kind'], step: string, result: AgentEvent['result'], summary = step): AgentEvent => ({
  event_id: `e${seq}`,
  item: 'ap:X',
  seq,
  ts: '2026-10-03T10:00:00Z',
  kind,
  step,
  result,
  summary,
})

describe('apCascade', () => {
  it('passes every check of a posted invoice', () => {
    const checks = apCascade({ decision: 'POST', reasons: [] })!
    expect(checks.every((c) => c.state === 'pass')).toBe(true)
  })

  it('fails at the first reason in cascade order and greys the rest', () => {
    const checks = apCascade({ decision: 'REJECT', reasons: ['WITHHOLDING_MISSING', 'VAT_RATE_INCORRECT'] })!
    const states = checks.map((c) => `${c.step.step}:${c.state}`)
    expect(states.slice(0, 5)).toEqual(['duplicate:pass', 'mandatory_fields:pass', 'addressee:pass', 'isp:pass', 'vat_rate:fail'])
    expect(checks.slice(5).every((c) => c.state === 'skipped')).toBe(true)
    expect(checks[4].detail).toBe('Tipo de IVA incorrecto')
  })

  it('stops at the IBAN check for a changed bank account', () => {
    const checks = apCascade({ decision: 'HOLD', reasons: ['BANK_DETAILS_CHANGED'] })!
    expect(checks.findIndex((c) => c.state === 'fail')).toBe(10)
  })

  it('names the original of a duplicate and blocks payment at §2.2.4', () => {
    expect(apCascade({ decision: 'DUPLICATE', duplicate_of: 'A1', reasons: ['DUPLICATE'] })![0]).toMatchObject({ state: 'fail', detail: 'Duplicado de A1' })
    const block = apCascade({ decision: 'POST_PAYMENT_BLOCK', reasons: [], payment_block: 'CONTRACTOR_CERTIFICATE_EXPIRED' })!
    expect(block.find((c) => c.state === 'fail')?.step.section).toBe('§2.2.4')
  })

  it('is not applicable to documents that are not invoices', () => {
    expect(apCascade({ decision: 'NOT_INVOICE', reasons: [] })).toBeNull()
  })

  it('prefers real agent events over the reconstruction', () => {
    const checks = apCascade({ decision: 'POST', reasons: [] } as Partial<ApRow>, [ev(1, 'CHECK', 'price', 'PASS', 'Precio dentro del 2 %')])!
    expect(checks.find((c) => c.step.step === 'price')).toMatchObject({ fromEvent: true, detail: 'Precio dentro del 2 %' })
  })
})

describe('reasoningSteps', () => {
  it('folds the §2.2 checks into one cascade step, in order', () => {
    const events = [
      ev(1, 'CLASSIFY', 'document_type', 'INFO'),
      ev(2, 'CHECK', 'duplicate', 'PASS'),
      ev(3, 'CHECK', 'mandatory_fields', 'FAIL'),
      ev(4, 'DECIDE', 'decision', 'INFO'),
    ]
    const steps = reasoningSteps(events, apCascade({ decision: 'REJECT', reasons: ['MANDATORY_FIELD_MISSING'] }))
    expect(steps.map((s) => s.kind)).toEqual(['CLASSIFY', 'CASCADE', 'DECIDE'])
    expect(steps[1].result).toBe('FAIL')
    expect(steps[1].title).toBe('Cascada §2.2: se detiene en «NIF del destinatario» (2 de 14)')
  })

  it('inserts the cascade before the decision when no event covers it', () => {
    const steps = reasoningSteps([ev(1, 'EXTRACT', 'header', 'INFO'), ev(2, 'DECIDE', 'decision', 'INFO')], apCascade({ decision: 'POST', reasons: [] }))
    expect(steps.map((s) => s.kind)).toEqual(['EXTRACT', 'CASCADE', 'DECIDE'])
    expect(steps[1].title).toBe('Cascada §2.2: supera las 14 comprobaciones')
  })

  it('keeps non-AP traces as they are', () => {
    expect(reasoningSteps([ev(2, 'POST', 'je', 'PASS'), ev(1, 'MATCH', 'm', 'PASS')]).map((s) => s.kind)).toEqual(['MATCH', 'POST'])
  })
})

describe('reasoningSummary on the fixture', () => {
  const core = fixtureCore()
  const run = fixtureRun()
  const derived = deriveRun(core, run, null)
  const summary = (id: string) => {
    const item = derived.itemsById.get(id)!
    const d = run.deliverables[item.task] as unknown[]
    const out = reasoningSummary({ item, rows: [d[item.rowIndex]], core, entries: itemEntries(core, run, id) })
    return { ...out, headline: nbsp(out.headline), facts: out.facts.map((f) => ({ ...f, text: f.text && nbsp(f.text) })) }
  }

  it('AP explains the decision from the cascade', () => {
    expect(summary('ap:A1').headline).toBe('Supera las 14 comprobaciones de la §2.2 y se contabiliza con un asiento de 3 líneas. Pago al factor.')
    expect(summary('ap:A4').headline).toBe('Retenida en la comprobación 11 de 14: IBAN distinto al de la ficha (§2.2.3).')
    expect(summary('ap:A6').headline).toBe('No es una factura (Cambio de cuenta bancaria): actualizar datos bancarios.')
  })

  it('bank, AR cash, IC and close get their own sentence', () => {
    expect(summary('bank_rec:BIN-1000/BL1').headline).toBe('Casada 1:N: 1 línea del extracto con 2 apuntes del libro.')
    expect(summary('bank_rec:BIN-1000/BL3').headline).toBe('Sin casar en el extracto: comisión sin contabilizar; se corrige con un asiento de ajuste (§4).')
    expect(summary('ar_cash:BL5').headline).toBe('El cobro de 300,00 € no viene de un cliente: indemnización de seguro (75900000).')
    const ic = summary('ic:1000-3100/INTEREST_DAY_COUNT')
    expect(ic.facts.find((f) => f.label === 'Intereses act/360')?.text).toContain('= 5.166,67 €')
    expect(summary('close:ACCRUAL/1000/V1').facts.find((f) => f.label === 'Periodo de referencia')?.text).toBe('1 may 2026 – 30 jun 2026')
  })
})

describe('bank helpers', () => {
  it('describes date gap and amount difference of a match', () => {
    expect(bankMatchDetail([{ booking_date: '2026-07-05', amount: -100 }], [{ id: 'J#1', date: '2026-07-05', amount: -100 }])).toBe('mismo día, importe exacto')
    expect(nbsp(bankMatchDetail([{ booking_date: '2026-07-05', amount: -1000 }], [{ id: 'J#1', date: '2026-07-03', amount: -183 }]))).toBe('a 2 días, diferencia de 8,17 €')
  })

  it('computes KMI interest with the day-count basis', () => {
    expect(loanInterest(500_000_000, 600, 31) - loanInterest(500_000_000, 600, 30)).toBe(83_333)
  })
})
