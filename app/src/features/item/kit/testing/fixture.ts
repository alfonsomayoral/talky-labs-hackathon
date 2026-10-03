// Small dataset + run covering every task, for the kit and ItemPanel tests.

import type { DatasetCore, Deliverables, RunBundle, TaskKey } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'

const je = (company: string, lines: [string, number, number, Record<string, unknown>?][]) => ({
  company,
  lines: lines.map(([account, debit, credit, extra]) => ({ account, debit, credit, partner: null, cost_center: null, wbs: null, ...extra })),
})

export function fixtureCore(): DatasetCore {
  const core = {
    companies: [
      { code: '1000', name: 'Kalmora Holding', short: 'Holding', country: 'ES', currency: 'EUR', role: '', city: '', street: '', postal_code: '', tax_id: 'A0000000', vat_id: '', partners: null },
      { code: '1100', name: 'Kalmora Obras', short: 'Obras', country: 'ES', currency: 'EUR', role: '', city: '', street: '', postal_code: '', tax_id: 'B1100000', vat_id: '', partners: null },
      { code: '3100', name: 'Kalmora México', short: 'México', country: 'MX', currency: 'MXN', role: '', city: '', street: '', postal_code: '', tax_id: 'KMX', vat_id: '', partners: null },
    ],
    chartOfAccounts: [
      { account: '60000000', description: 'Compras', type: 'PL', open_items: false },
      { account: '62600000', description: 'Servicios bancarios', type: 'PL', open_items: false },
    ],
    taxCodes: { tax_codes: {}, withholdings: {}, customer_deductions: {} },
    costCenters: [],
    projects: [],
    vendors: [
      { id: 'V1', name: 'Proveedor Uno, S.L.', tax_id: 'B111', email: 'facturas@uno.es', bank: { iban: 'ES1100000000000000000001' }, bank_history: [], companies: ['1000'] },
      { id: 'V2', name: 'Proveedor Dos, S.A.', tax_id: 'B222', email: 'admin@dos.es', bank: { iban: 'ES2200000000000000000002' }, bank_history: [], companies: ['1000'] },
    ],
    contractorCertificates: [{ vendor: 'V2', issued_on: '2025-01-01', valid_until: '2026-06-30', reference: 'CERT-1' }],
    customers: [
      { id: 'C1', name: 'Cliente Uno', tax_id: 'C111', country: 'ES', kind: 'PRIVATE', address: { street: '', city: '' }, currency: 'EUR', iban: null },
      { id: 'C2', name: 'Ayuntamiento Dos', tax_id: 'P222', country: 'ES', kind: 'PUBLIC', address: { street: '', city: '' }, currency: 'EUR', iban: null },
    ],
    salesContracts: [],
    purchaseOrders: [],
    openItems: [],
    apInvoices: [],
    apDocumentLog: [],
    arInvoices: [
      { id: 'F1', company: '1000', customer: 'C1', payable: 25000 },
      { id: 'F2', company: '1000', customer: 'C2', payable: 10000 },
      { id: 'F3', company: '1000', customer: 'C2', payable: 15000 },
    ],
    billingHistory: [],
    promissoryNotes: [],
    factoringAssignments: [],
    sepaRemittances: [],
    penaltyNotices: [],
    intercompanyAgreements: {
      management_fees: {},
      loan: { id: 'KMI-2025-01', principal: 100_000_000, rate_bp: 600, basis: 'act/360', start: '2025-01-01', lender: '1000', borrower: '3100', note: '' },
      cash_pooling: { header: '1000', participants: ['1100'], scheme: 'zero', interest: '' },
      ute: {},
    },
    fxRates: [{ date: '2026-07-31', base: 'EUR', currency: 'MXN', rate: 20, source: 'SYN-BCE' }],
    bankAccounts: [{ id: 'BIN-1000', company: '1000', bank: 'Banco Uno', bic: 'B1', iban: 'ES9900', clabe: null, gl_account: '57200001', currency: 'EUR', statement_format: 'n43', roles: [] }],
    tasks: {
      ap_documents: ['A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'A8'],
      ar_billing_items: ['B1', 'B2', 'B3'],
      ar_receipts: ['BL4', 'BL5', 'BL6'],
      bank_accounts: ['BIN-1000'],
      intercompany: { pairs: [['1000', '1100'], ['1000', '3100'], ['1100', '1910']], accounts: [] },
      close: { month: '2026-07', steps: ['ACCRUAL', 'PREPAID', 'FX_REVAL'] },
    },
    apInbox: [
      {
        docId: 'A1',
        message: { doc_id: 'A1', channel: 'email', received_at: '2026-07-02T10:00:00', mailbox: 'ap@k', attachments: ['f.pdf'], from: 'facturas@uno.es', subject: 'Factura 1' },
        files: ['inbox/ap/A1/f.pdf'],
      },
      {
        docId: 'A4',
        message: { doc_id: 'A4', channel: 'email', received_at: '2026-07-03T10:00:00', mailbox: 'ap@k', attachments: ['f.pdf'], from: 'facturas@uno-es.es', subject: 'Nueva cuenta' },
        files: ['inbox/ap/A4/f.pdf'],
      },
    ],
    arInbox: { billing: [], remittances: [], notices: [] },
    bankStatements: [
      {
        account: 'BIN-1000',
        month: '2026-07',
        format: 'n43',
        rawPath: null,
        lines: [
          { bank_line: 'BL1', booking_date: '2026-07-05', value_date: '2026-07-05', amount: -100000, currency: 'EUR', text: 'REMESA PAGOS' },
          { bank_line: 'BL2', booking_date: '2026-07-06', value_date: '2026-07-06', amount: 50000, currency: 'EUR', text: 'TRANSFERENCIA' },
          { bank_line: 'BL3', booking_date: '2026-07-07', value_date: '2026-07-07', amount: -2000, currency: 'EUR', text: 'COMISION' },
          { bank_line: 'BL4', booking_date: '2026-07-08', value_date: '2026-07-08', amount: 25000, currency: 'EUR', text: 'COBRO CLIENTE UNO' },
          { bank_line: 'BL5', booking_date: '2026-07-09', value_date: '2026-07-09', amount: 30000, currency: 'EUR', text: 'INDEMNIZACION SEGURO' },
          { bank_line: 'BL6', booking_date: '2026-07-10', value_date: '2026-07-10', amount: 24000, currency: 'EUR', text: 'AYUNTAMIENTO DOS' },
        ],
      },
    ],
    golden: null,
  }
  return core as unknown as DatasetCore
}

const apRow = (doc_id: string, decision: string, extra: Record<string, unknown> = {}) => ({
  doc_id,
  document_type: 'INVOICE',
  decision,
  reasons: [],
  company: '1000',
  vendor_id: 'V1',
  invoice_number: `N-${doc_id}`,
  invoice_date: '2026-07-01',
  currency: 'EUR',
  net: 10000,
  tax: 2100,
  gross: 12100,
  withholding: 0,
  retention: 0,
  payable: 12100,
  duplicate_of: null,
  payee: null,
  payment_block: null,
  action: null,
  lines: [{ amount: 10000, account: '60000000', cost_center: 'CC-1', wbs: null, tax_code: 'S21' }],
  journal_entry: null,
  ...extra,
})

const postedJe = je('1000', [
  ['60000000', 10000, 0, { cost_center: 'CC-1' }],
  ['47200000', 2100, 0],
  ['40000000', 0, 12100, { partner: 'V1' }],
])

export function fixtureDeliverables(): Deliverables {
  const d = {
    ap: [
      apRow('A1', 'POST', { journal_entry: postedJe, payee: { type: 'FACTOR' } }),
      apRow('A2', 'REJECT', { reasons: ['ISP_NOT_APPLIED'] }),
      apRow('A3', 'REJECT', { reasons: ['WITHHOLDING_MISSING', 'VAT_RATE_INCORRECT'] }),
      apRow('A4', 'HOLD', { reasons: ['BANK_DETAILS_CHANGED'] }),
      apRow('A5', 'DUPLICATE', { reasons: ['DUPLICATE'], duplicate_of: 'A1' }),
      apRow('A6', 'NOT_INVOICE', { document_type: 'BANK_DETAILS_CHANGE', action: 'UPDATE_BANK_DETAILS', lines: [] }),
      apRow('A7', 'POST_PAYMENT_BLOCK', { vendor_id: 'V2', payment_block: 'CONTRACTOR_CERTIFICATE_EXPIRED', journal_entry: postedJe }),
      apRow('A8', 'POST', { document_type: 'CREDIT_NOTE', journal_entry: je('1000', [['40000000', 5000, 0, { partner: 'V1' }], ['60000000', 0, 5000]]) }),
    ],
    ar_billing: [
      {
        billing_item: 'B1',
        type: 'OBRA_CERTIFICATION',
        company: '1000',
        customer: 'C2',
        contract: 'CV-1',
        expected: 'INVOICE',
        invoice: {
          date: '2026-07-31',
          due_date: '2026-08-30',
          tax_code: 'R21',
          net: 100000,
          tax: 21000,
          gross: 121000,
          retention: 0,
          deductions: [],
          payable: 121000,
          face: { oficina_contable: 'L1', organo_gestor: 'L2', unidad_tramitadora: 'L3' },
          lines: [{ description: 'Capítulo 1', amount: 100000, account: '70510000', wbs: 'OB-1' }],
        },
        journal_entry: je('1000', [['43000000', 121000, 0, { partner: 'C2' }], ['70510000', 0, 100000, { wbs: 'OB-1' }], ['47700000', 0, 21000]]),
      },
      { billing_item: 'B2', type: 'OBRA_CERTIFICATION', company: '1000', customer: 'C1', contract: 'CV-2', expected: 'SKIP_PENDING_APPROVAL', invoice: null, journal_entry: null },
      {
        billing_item: 'B3',
        type: 'SERVICE_MONTHLY',
        company: '1000',
        customer: 'C1',
        contract: 'CT-3',
        expected: 'INVOICE',
        invoice: { date: '2026-07-31', due_date: '2026-08-30', tax_code: 'R10', net: 1000, tax: 100, gross: 1100, retention: 0, deductions: [], payable: 1100, face: null, lines: [] },
        journal_entry: je('1000', [['43000000', 1100, 0, { partner: 'C1' }], ['70500000', 0, 1000], ['47700000', 0, 100]]),
      },
    ],
    ar_cash: [
      {
        bank_line: 'BL4',
        customer: 'C1',
        applications: [{ invoice: 'F1', amount: 25000 }],
        residuals: [],
        adjustment: [
          { company: '1000', account: '55500000', debit: 25000, credit: 0 },
          { company: '1000', account: '43000000', debit: 0, credit: 25000, partner: 'C1' },
        ],
      },
      {
        bank_line: 'BL5',
        customer: null,
        applications: [],
        residuals: [{ type: 'NON_CUSTOMER', amount: 30000, account: '75900000' }],
        adjustment: [
          { company: '1000', account: '55500000', debit: 30000, credit: 0 },
          { company: '1000', account: '75900000', debit: 0, credit: 30000 },
        ],
      },
      {
        bank_line: 'BL6',
        customer: 'C2',
        applications: [
          { invoice: 'F2', amount: 10000 },
          { invoice: 'F3', amount: 15000 },
        ],
        residuals: [{ type: 'PENALTY', invoice: 'F3', amount: -1000 }],
        adjustment: [
          { company: '1000', account: '55500000', debit: 24000, credit: 0 },
          { company: '1000', account: '70590000', debit: 1000, credit: 0 },
          { company: '1000', account: '43000000', debit: 0, credit: 25000, partner: 'C2' },
        ],
      },
    ],
    bank_rec: [
      {
        account: 'BIN-1000',
        company: '1000',
        matches: [
          { bank_lines: ['BL1'], book_lines: ['J1#2', 'J2#2'] },
          { bank_lines: ['BL2'], book_lines: ['J3#1'] },
        ],
        unmatched_bank: [{ bank_line: 'BL3', category: 'BANK_FEE_NOT_BOOKED' }],
        unmatched_book: [{ book_line: 'J4#2', category: 'OUTSTANDING_PAYMENT' }],
        adjustments: [
          {
            category: 'BANK_FEE_NOT_BOOKED',
            lines: [
              { company: '1000', account: '62600000', debit: 2000, credit: 0 },
              { company: '1000', account: '57200001', debit: 0, credit: 2000 },
            ],
          },
        ],
      },
    ],
    ic: [
      {
        pair: ['3100', '1000'],
        cause: 'INTEREST_DAY_COUNT',
        amount: 8333,
        responsible: '3100',
        adjustment: [
          { company: '3100', account: '66210000', debit: 166660, credit: 0 },
          { company: '3100', account: '55200000', debit: 0, credit: 166660, partner: '1000' },
        ],
      },
      { pair: ['1000', '1100'], cause: 'POOLING_NOT_BOOKED', amount: 50000, responsible: '1100', adjustment: [] },
    ],
    close: [
      {
        type: 'ACCRUAL',
        company: '1000',
        vendor: 'V1',
        invoice: 'API1',
        period: ['2026-05-01', '2026-06-30'],
        amount: 30000,
        journal_entry: je('1000', [['62800000', 30000, 0, { cost_center: 'CC-1' }], ['40090000', 0, 30000, { partner: 'V1' }]]),
      },
      {
        type: 'FX_REVAL',
        company: '3100',
        item: 'GL:16330000',
        currency: 'EUR',
        foreign: 100_000_000,
        rate: 20,
        amount: -200000,
        journal_entry: je('3100', [['16330000', 200000, 0, { partner: '1000' }], ['76800000', 0, 200000]]),
      },
    ],
  }
  return d as unknown as Deliverables
}

export function fixtureRun(overrides: Partial<RunBundle> = {}): RunBundle {
  return {
    id: 'fixture',
    datasetId: 'fixture',
    source: 'import',
    label: 'Fixture',
    createdAt: '2026-10-03T10:00:00Z',
    manifest: null,
    deliverables: fixtureDeliverables(),
    present: Object.fromEntries(TASK_KEYS.map((k) => [k, true])) as Record<TaskKey, boolean>,
    events: null,
    attention: null,
    ...overrides,
  }
}
