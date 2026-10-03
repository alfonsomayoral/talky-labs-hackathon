// Catalog of every code in the deliverables → Spanish label, section of
// POLITICAS_CONTABLES.md and one-sentence description. Views and the engine read it.

import type {
  ApAction,
  ApDecision,
  ApDocumentType,
  ApReason,
  ArResidualType,
  AttentionKind,
  BankCategory,
  ChartAccount,
  CloseType,
  IcCause,
  Priority,
  TaskKey,
} from '@/domain/types'

export interface PolicyEntry {
  label: string
  section: string
  description: string
  /** Default attention when the code shows up (PLAN §5). */
  attention?: { kind: AttentionKind; priority: Priority }
}

const P2_POLICY = { kind: 'POLICY_EXCEPTION', priority: 'P2' } as const
const P2_MASTER = { kind: 'MASTER_DATA', priority: 'P2' } as const
const P1_CROSS = { kind: 'CROSS_TASK', priority: 'P1' } as const
const P1_ESTIMATE = { kind: 'ESTIMATE', priority: 'P1' } as const

// ---------------------------------------------------------------- AP
export const AP_REASON_CATALOG: Record<ApReason, PolicyEntry> = {
  DUPLICATE: {
    label: 'Duplicado',
    section: '§2.2.1',
    description: 'Mismo proveedor, número de factura normalizado e importe que un documento ya recibido en el histórico o antes en el mes.',
  },
  MANDATORY_FIELD_MISSING: {
    label: 'Falta el NIF del destinatario',
    section: '§2.2.2',
    description: 'Falta el NIF del destinatario: hay que pedir una factura nueva al proveedor.',
    attention: P2_POLICY,
  },
  WRONG_ADDRESSEE: {
    label: 'Destinatario incorrecto',
    section: '§2.2.2',
    description: 'La factura va dirigida a otra sociedad del grupo (o a 1100 en vez de a la UTE 1910) distinta de la que hizo el pedido.',
    attention: P2_POLICY,
  },
  ISP_NOT_APPLIED: {
    label: 'ISP no aplicada',
    section: '§2.2.2',
    description: 'Un subcontratista de obra repercute IVA cuando procede la inversión del sujeto pasivo.',
    attention: P2_POLICY,
  },
  VAT_RATE_INCORRECT: {
    label: 'Tipo de IVA incorrecto',
    section: '§2.2.2',
    description: 'El tipo de IVA no es el aplicable: residuos, limpieza viaria y agua llevan el 10 % y el resto el 21 %.',
    attention: P2_POLICY,
  },
  WITHHOLDING_MISSING: {
    label: 'Falta la retención',
    section: '§2.2.2',
    description: 'Un profesional persona física o un arrendador urbano no practica la retención.',
    attention: P2_POLICY,
  },
  ARITHMETIC_ERROR: {
    label: 'Error aritmético',
    section: '§2.2.2',
    description: 'El total de la factura no es la base más las cuotas.',
    attention: P2_POLICY,
  },
  CERTIFICATION_CUMULATIVE_BILLED: {
    label: 'Certificación facturada a origen',
    section: '§2.2.2',
    description: 'La subcontrata factura el importe a origen en vez del de esta certificación.',
    attention: P2_POLICY,
  },
  CFDI_MISMATCH: {
    label: 'CFDI distinto del PDF',
    section: '§2.2.2',
    description: 'El XML del CFDI no coincide con el PDF de la factura.',
    attention: P2_POLICY,
  },
  VENDOR_NOT_IN_MASTER: {
    label: 'Proveedor sin alta',
    section: '§2.2.3',
    description: 'El proveedor no está dado de alta en el maestro.',
    attention: P2_POLICY,
  },
  BANK_DETAILS_CHANGED: {
    label: 'IBAN distinto al de la ficha',
    section: '§2.2.3',
    description:
      'El IBAN de la factura difiere del de la ficha sin carta de cambio firmada ni cesión a un factor, o el correo viene de un dominio parecido: posible fraude.',
    attention: { kind: 'FRAUD_SIGNAL', priority: 'P0' },
  },
  QTY_NOT_RECEIVED: {
    label: 'Cantidad sin recibir',
    section: '§2.2.3',
    description: 'Algún albarán facturado no tiene entrada de mercancía.',
    attention: P2_POLICY,
  },
  PRICE_VARIANCE: {
    label: 'Desviación de precio',
    section: '§2.2.3',
    description: 'El precio unitario supera el del pedido en más del 2 % o en más de 150 € por línea.',
    attention: P2_POLICY,
  },
  CONTRACTOR_CERTIFICATE_EXPIRED: {
    label: 'Certificado art. 43 caducado',
    section: '§2.2.4',
    description: 'El subcontratista de obra no tiene certificado del art. 43 vigente a la fecha de la factura: se contabiliza con bloqueo de pago.',
  },
}

export const AP_DECISION_CATALOG: Record<ApDecision, PolicyEntry> = {
  POST: {
    label: 'Contabilizar',
    section: '§2.2.5',
    description: 'Supera todas las comprobaciones y se contabiliza; una diferencia de precio dentro de tolerancia va al mismo gasto u objeto de coste.',
  },
  POST_PAYMENT_BLOCK: {
    label: 'Contabilizar con bloqueo de pago',
    section: '§2.2.4',
    description: 'Se contabiliza, pero el pago queda bloqueado porque el subcontratista no tiene certificado del art. 43 vigente.',
  },
  HOLD: {
    label: 'Retener',
    section: '§2.2.3',
    description: 'No se contabiliza todavía: proveedor sin alta, IBAN cambiado, cantidad sin recibir o desviación de precio.',
    attention: P2_POLICY,
  },
  REJECT: {
    label: 'Rechazar',
    section: '§2.2.2',
    description: 'Hay que pedir una factura nueva al proveedor.',
    attention: P2_POLICY,
  },
  DUPLICATE: {
    label: 'Duplicado',
    section: '§2.2.1',
    description: 'El documento ya se recibió antes y se enlaza con el primero en duplicate_of.',
  },
  NOT_INVOICE: {
    label: 'No es factura',
    section: '§2.1',
    description: 'El documento no es una factura: no se contabiliza y solo se registra su acción.',
  },
}

export const AP_DOCUMENT_TYPE_CATALOG: Record<ApDocumentType, PolicyEntry> = {
  INVOICE: { label: 'Factura', section: '§2.1', description: 'Factura ordinaria (PDF, Facturae XML o CFDI) que se decide según la §2.2.' },
  CREDIT_NOTE: {
    label: 'Abono',
    section: '§2.1',
    description: 'Factura rectificativa o abono: asiento inverso imputado a la misma cuenta y objeto de coste.',
  },
  DOWN_PAYMENT_REQUEST: {
    label: 'Solicitud de anticipo',
    section: '§2.1',
    description: 'Solicitud de anticipo de un proveedor extranjero con pedido aprobado: Dr 40700000 / Cr 40000000.',
  },
  PROFORMA: { label: 'Proforma', section: '§2.1', description: 'Proforma u oferta: no es factura y no requiere acción.' },
  VENDOR_STATEMENT: {
    label: 'Extracto de proveedor',
    section: '§2.1',
    description: 'Extracto o recordatorio de deuda: no es factura y no requiere acción.',
  },
  FACTORING_NOTICE: {
    label: 'Notificación de cesión',
    section: '§2.1',
    description: 'Notificación de cesión de créditos: se registra el factor como beneficiario alternativo.',
  },
  TAX_GARNISHMENT_ORDER: {
    label: 'Diligencia de embargo',
    section: '§2.1',
    description: 'Diligencia de embargo de la AEAT: se registra el embargo sobre los pagos al proveedor.',
  },
  BANK_DETAILS_CHANGE: {
    label: 'Cambio de cuenta bancaria',
    section: '§2.1',
    description: 'Carta firmada de cambio de cuenta con certificado bancario: se actualizan los datos bancarios de la ficha.',
  },
  CONTRACTOR_TAX_CERTIFICATE: {
    label: 'Certificado art. 43',
    section: '§2.1',
    description: 'Certificado de estar al corriente (art. 43.1.f LGT): se actualiza el certificado del subcontratista.',
  },
}

export const AP_ACTION_CATALOG: Record<ApAction, PolicyEntry> = {
  NONE: { label: 'Sin acción', section: '§2.1', description: 'El documento no requiere ninguna acción.' },
  REGISTER_ALTERNATIVE_PAYEE: {
    label: 'Registrar beneficiario alternativo',
    section: '§2.1',
    description: 'Registrar al factor como beneficiario de los pagos al proveedor.',
    attention: P2_MASTER,
  },
  REGISTER_EMBARGO: {
    label: 'Registrar embargo',
    section: '§2.1',
    description: 'Registrar la diligencia de embargo para pagar a la AEAT.',
    attention: P2_MASTER,
  },
  UPDATE_BANK_DETAILS: {
    label: 'Actualizar datos bancarios',
    section: '§2.1',
    description: 'Actualizar el IBAN de la ficha con la carta firmada y el certificado bancario.',
    attention: P2_MASTER,
  },
  UPDATE_CONTRACTOR_CERTIFICATE: {
    label: 'Actualizar certificado art. 43',
    section: '§2.1',
    description: 'Actualizar en el maestro la vigencia del certificado del subcontratista.',
  },
}

export const AP_PAYEE_CATALOG: Record<'FACTOR' | 'AEAT_EMBARGO', PolicyEntry> = {
  FACTOR: { label: 'Pago al factor', section: '§2.2', description: 'Hay una cesión de créditos vigente a la fecha de la factura: el pago va al factor.' },
  AEAT_EMBARGO: {
    label: 'Pago a la AEAT',
    section: '§2.2',
    description: 'Hay una diligencia de embargo recibida antes que la factura: el pago va a la AEAT.',
  },
}

export type CascadeGroup = 'duplicate' | 'reject' | 'hold' | 'payment_block' | 'post'

export interface CascadeStep {
  /** Step id used in events (`step`). */
  step: string
  /** Reason that fails at this step (`POST` for the final step). */
  code: ApReason | 'POST'
  group: CascadeGroup
  decision: ApDecision
  label: string
  section: string
}

/** §2.2 checks in order: the first one that fails decides. */
export const AP_CASCADE: readonly CascadeStep[] = [
  { step: 'duplicate', code: 'DUPLICATE', group: 'duplicate', decision: 'DUPLICATE', label: 'Duplicados', section: '§2.2.1' },
  { step: 'mandatory_fields', code: 'MANDATORY_FIELD_MISSING', group: 'reject', decision: 'REJECT', label: 'NIF del destinatario', section: '§2.2.2' },
  { step: 'addressee', code: 'WRONG_ADDRESSEE', group: 'reject', decision: 'REJECT', label: 'Sociedad destinataria', section: '§2.2.2' },
  { step: 'isp', code: 'ISP_NOT_APPLIED', group: 'reject', decision: 'REJECT', label: 'Inversión del sujeto pasivo', section: '§2.2.2' },
  { step: 'vat_rate', code: 'VAT_RATE_INCORRECT', group: 'reject', decision: 'REJECT', label: 'Tipo de IVA', section: '§2.2.2' },
  { step: 'withholding', code: 'WITHHOLDING_MISSING', group: 'reject', decision: 'REJECT', label: 'Retención IRPF', section: '§2.2.2' },
  { step: 'arithmetic', code: 'ARITHMETIC_ERROR', group: 'reject', decision: 'REJECT', label: 'Base más cuotas', section: '§2.2.2' },
  {
    step: 'certification',
    code: 'CERTIFICATION_CUMULATIVE_BILLED',
    group: 'reject',
    decision: 'REJECT',
    label: 'Importe de esta certificación',
    section: '§2.2.2',
  },
  { step: 'cfdi', code: 'CFDI_MISMATCH', group: 'reject', decision: 'REJECT', label: 'CFDI frente a PDF', section: '§2.2.2' },
  { step: 'vendor_master', code: 'VENDOR_NOT_IN_MASTER', group: 'hold', decision: 'HOLD', label: 'Proveedor dado de alta', section: '§2.2.3' },
  { step: 'bank_details', code: 'BANK_DETAILS_CHANGED', group: 'hold', decision: 'HOLD', label: 'IBAN frente a la ficha', section: '§2.2.3' },
  { step: 'goods_receipt', code: 'QTY_NOT_RECEIVED', group: 'hold', decision: 'HOLD', label: 'Entrada de mercancía', section: '§2.2.3' },
  { step: 'price', code: 'PRICE_VARIANCE', group: 'hold', decision: 'HOLD', label: 'Precio frente al pedido', section: '§2.2.3' },
  {
    step: 'contractor_certificate',
    code: 'CONTRACTOR_CERTIFICATE_EXPIRED',
    group: 'payment_block',
    decision: 'POST_PAYMENT_BLOCK',
    label: 'Certificado art. 43 vigente',
    section: '§2.2.4',
  },
  { step: 'post', code: 'POST', group: 'post', decision: 'POST', label: 'Contabilizar', section: '§2.2.5' },
]

// ---------------------------------------------------------------- AR
export const AR_BILLING_OUTCOME_CATALOG: Record<'INVOICE' | 'SKIP_PENDING_APPROVAL', PolicyEntry> = {
  INVOICE: { label: 'Facturar', section: '§3.1', description: 'Se emite la factura del mes con sus impuestos, retenciones y asiento.' },
  SKIP_PENDING_APPROVAL: {
    label: 'Pendiente de aprobación',
    section: '§3.1',
    description: 'La certificación no está aprobada por la Dirección Facultativa: no se factura y el cierre registra la obra pendiente de certificar.',
    attention: P2_POLICY,
  },
}

export type ArCashOutcome = 'APPLIED' | 'APPLIED_WITH_DIFFERENCES' | 'PARTIAL' | 'NOT_APPLIED'

export const AR_CASH_OUTCOME_CATALOG: Record<ArCashOutcome, PolicyEntry> = {
  APPLIED: { label: 'Aplicado', section: '§3.2', description: 'El abono se aplica entero a facturas o pagarés del cliente desde 55500000.' },
  APPLIED_WITH_DIFFERENCES: {
    label: 'Aplicado con diferencias',
    section: '§3.2',
    description: 'El abono se aplica y la diferencia se explica con una causa conocida (penalidad, compensación, pago duplicado…).',
  },
  PARTIAL: {
    label: 'Aplicación parcial',
    section: '§3.2',
    description: 'El cliente paga menos sin causa conocida: se aplica parcialmente a la factura y el resto queda abierto.',
    attention: { kind: 'MATERIAL_UNEXPLAINED', priority: 'P2' },
  },
  NOT_APPLIED: { label: 'Sin aplicar', section: '§3.2', description: 'El abono no se aplica a ninguna factura ni diferencia.' },
}

export const AR_RESIDUAL_CATALOG: Record<ArResidualType, PolicyEntry> = {
  PENALTY: { label: 'Penalidad', section: '§3.2', description: 'Penalidad descontada por la administración: Dr 70590000.' },
  NETTING_AP: {
    label: 'Compensación con proveedor',
    section: '§3.2',
    description: 'Compensación con una factura de honorarios del propio cliente: Dr a la cuenta del proveedor.',
  },
  OVERPAYMENT_DUPLICATE: {
    label: 'Pago duplicado',
    section: '§3.2',
    description: 'El cliente pagó dos veces: Cr 43800000, a devolver o compensar.',
    attention: { kind: 'POLICY_EXCEPTION', priority: 'P1' },
  },
  FACTORED_MISDIRECTED: {
    label: 'Factura cedida cobrada por error',
    section: '§3.2',
    description: 'El cliente pagó a Kalmora una factura cedida al factor: Cr 55300000 con socio FACTOR-BAE.',
  },
  NON_CUSTOMER: {
    label: 'No es un cliente',
    section: '§3.2',
    description: 'El cobro no viene de un cliente: indemnización de seguro (75900000), devolución de fianza (56500000) o de IVA (47000000).',
    attention: { kind: 'DATA_QUALITY', priority: 'P1' },
  },
}

// ---------------------------------------------------------------- Bank
export interface BankCategoryEntry extends PolicyEntry {
  side: 'bank' | 'book' | 'both' | 'difference'
  adjustment: boolean
}

export const BANK_MATCH_ENTRY: PolicyEntry = {
  label: 'Casado',
  section: '§4',
  description: 'Línea del extracto casada con apuntes de la cuenta 572 (1:1, N:1 o 1:N).',
}

export const BANK_CATEGORY_CATALOG: Record<BankCategory, BankCategoryEntry> = {
  BANK_FEE_NOT_BOOKED: {
    label: 'Comisión sin contabilizar',
    section: '§4',
    description: 'Comisión cargada por el banco y no registrada: Dr 62600000 (comisiones de aval: 66900000) / Cr 572.',
    side: 'bank',
    adjustment: true,
  },
  INTEREST_NOT_BOOKED: {
    label: 'Intereses sin contabilizar',
    section: '§4',
    description: 'Intereses abonados y no registrados: Dr 572 / Cr 76200000, con la retención del 19 % a 47300000.',
    side: 'bank',
    adjustment: true,
  },
  LOAN_INTEREST_NOT_BOOKED: {
    label: 'Intereses de préstamo sin contabilizar',
    section: '§4',
    description: 'Intereses de préstamo cargados y no registrados: Dr 66200000 / Cr 572.',
    side: 'difference',
    adjustment: true,
  },
  CARD_SETTLEMENT_NOT_BOOKED: {
    label: 'Liquidación de tarjeta sin contabilizar',
    section: '§4',
    description: 'Liquidación de tarjeta no registrada: Dr 62910000 (CC-1000-DIR) / Cr 572.',
    side: 'bank',
    adjustment: true,
  },
  DIRECT_DEBIT_NOT_BOOKED: {
    label: 'Domiciliación sin contabilizar',
    section: '§4',
    description: 'Recibo domiciliado no registrado: Dr cuenta del proveedor (asignación = nº de factura) / Cr 572.',
    side: 'bank',
    adjustment: true,
  },
  RETURNED_DIRECT_DEBIT: {
    label: 'Recibo devuelto',
    section: '§4',
    description: 'Recibo de cliente devuelto: Dr 43000000 (asignación = recibo) / Cr 572, y la comisión a 62600000.',
    side: 'bank',
    adjustment: true,
  },
  FX_RATE_DIFFERENCE: {
    label: 'Diferencia de cambio',
    section: '§4',
    description: 'Diferencia entre el cambio aplicado por el banco y el de referencia: 66800000 o 76800000.',
    side: 'difference',
    adjustment: true,
  },
  FACTORING_CHARGES_NOT_BOOKED: {
    label: 'Gastos de factoring sin contabilizar',
    section: '§4',
    description: 'Gastos de factoring no registrados: Dr 66500000 / Cr 55300000.',
    side: 'difference',
    adjustment: true,
  },
  POOLING_NOT_BOOKED: {
    label: 'Barrido de pooling sin contabilizar',
    section: '§4',
    description: 'Barrido de cash pooling no registrado: se contabiliza contra 55200000 con socio 1000.',
    side: 'bank',
    adjustment: true,
    attention: P1_CROSS,
  },
  UNRECORDED_RECEIPT: {
    label: 'Cobro sin registrar',
    section: '§4',
    description: 'No se importó el N43 de ese día: Dr 572 / Cr 55500000.',
    side: 'bank',
    adjustment: true,
    attention: P1_CROSS,
  },
  BOOK_AMOUNT_ERROR: {
    label: 'Importe erróneo en libros',
    section: '§4',
    description: 'El importe registrado no coincide con el del banco: se corrige contra la cuenta del proveedor.',
    side: 'book',
    adjustment: true,
  },
  WRONG_BANK_ACCOUNT: {
    label: 'Cuenta bancaria equivocada',
    section: '§4',
    description: 'El movimiento se registró en otra cuenta 572: se reclasifica entre cuentas bancarias.',
    side: 'both',
    adjustment: true,
    attention: P1_CROSS,
  },
  BOOK_DUPLICATE: {
    label: 'Asiento duplicado',
    section: '§4',
    description: 'El movimiento se registró dos veces en libros: se anula el asiento duplicado.',
    side: 'book',
    adjustment: true,
  },
  BANK_ERROR: {
    label: 'Error del banco',
    section: '§4',
    description: 'Cargo duplicado por el banco: se reclama al banco sin ajuste contable.',
    side: 'bank',
    adjustment: false,
    attention: { kind: 'DATA_QUALITY', priority: 'P2' },
  },
  OUTSTANDING_PAYMENT: {
    label: 'Pago pendiente de cargo',
    section: '§4',
    description: 'Pago registrado que el banco ejecuta el mes siguiente.',
    side: 'book',
    adjustment: false,
  },
  TRANSFER_IN_TRANSIT: {
    label: 'Traspaso en tránsito',
    section: '§4',
    description: 'Traspaso entre cuentas propias pendiente de abono.',
    side: 'book',
    adjustment: false,
  },
  PRIOR_PERIOD_BANK_ITEM: {
    label: 'Partida del mes anterior',
    section: '§4',
    description: 'Registro de un cargo que salió en el extracto del mes anterior.',
    side: 'book',
    adjustment: false,
  },
  FX_REVALUATION: {
    label: 'Valoración en divisa',
    section: '§4',
    description: 'Valoración o retrocesión de saldos en divisa: no es un movimiento.',
    side: 'book',
    adjustment: false,
  },
}

// ---------------------------------------------------------------- Intercompany
export const IC_CAUSE_CATALOG: Record<IcCause, PolicyEntry> = {
  INVOICE_IN_TRANSIT: {
    label: 'Factura en tránsito',
    section: '§6',
    description: 'Factura intragrupo emitida y no recibida al cierre: el receptor registra Dr gasto / Cr 40090000.',
  },
  INTEREST_DAY_COUNT: {
    label: 'Base de días de los intereses',
    section: '§6',
    description: 'Los intereses del préstamo KMI-2025-01 se calcularon con una base distinta de act/360.',
  },
  WRONG_TRADING_PARTNER: {
    label: 'Socio intragrupo equivocado',
    section: '§6',
    description: 'El asiento se registró con otro socio intragrupo.',
  },
  DUPLICATE_POSTING: { label: 'Asiento duplicado', section: '§6', description: 'El asiento intragrupo se registró dos veces.' },
  POOLING_NOT_BOOKED: {
    label: 'Barrido sin registrar',
    section: '§6',
    description: 'Barrido de cash pooling sin registrar: se corrige en la conciliación bancaria y aquí va sin ajuste.',
    attention: P1_CROSS,
  },
}

// ---------------------------------------------------------------- Close
export const CLOSE_TYPE_CATALOG: Record<CloseType, PolicyEntry> = {
  ACCRUAL: {
    label: 'Periodificación',
    section: '§5',
    description: 'Servicio sin pedido consumido y no facturado al cierre, estimado con el histórico del proveedor (±15 %): Dr gasto / Cr 40090000.',
    attention: P1_ESTIMATE,
  },
  PREPAID: {
    label: 'Gasto anticipado',
    section: '§5',
    description: 'Primas, arrendamientos rústicos y cuotas anuales repartidos linealmente: la parte no devengada se difiere a 48000000.',
  },
  WIP_REVENUE: {
    label: 'Obra pendiente de certificar',
    section: '§5',
    description: 'Obra ejecutada con la certificación sin aprobar: Dr 43090000 / Cr 71300000, con retrocesión el día 1.',
  },
  FX_REVAL: {
    label: 'Valoración en divisa',
    section: '§5',
    description: 'Partidas abiertas en moneda extranjera valoradas al tipo SYN-BCE del último día del mes contra 66800000 o 76800000.',
    attention: P1_ESTIMATE,
  },
  BAD_DEBT: {
    label: 'Deterioro de clientes',
    section: '§5',
    description: 'Provisión del saldo de clientes privados: 50 % a más de 180 días y 100 % a más de 365 días o en concurso.',
    attention: P1_ESTIMATE,
  },
  DOUBTFUL_RECLASS: {
    label: 'Reclasificación a dudoso cobro',
    section: '§5',
    description: 'En el mes en que se declara el concurso, el saldo pasa de 43000000 a 43600000 factura a factura.',
  },
}

/** Close estimates above this amount (EUR cents) go to attention as P1 (PLAN §5). */
export const ESTIMATE_ATTENTION_THRESHOLD_EUR = 5_000_000

// ---------------------------------------------------------------- Lookups
const OUTCOME_CATALOGS: Record<TaskKey, Record<string, PolicyEntry>> = {
  ap: AP_DECISION_CATALOG,
  ar_billing: AR_BILLING_OUTCOME_CATALOG,
  ar_cash: AR_CASH_OUTCOME_CATALOG,
  bank_rec: { ...BANK_CATEGORY_CATALOG, MATCH: BANK_MATCH_ENTRY },
  ic: IC_CAUSE_CATALOG,
  close: CLOSE_TYPE_CATALOG,
}

const REASON_CATALOGS: Partial<Record<TaskKey, Record<string, PolicyEntry>>> = {
  ap: AP_REASON_CATALOG,
  ar_cash: AR_RESIDUAL_CATALOG,
  bank_rec: BANK_CATEGORY_CATALOG,
}

/** Catalog entry of a WorkItem outcome (AP decision, bank category, close type…). */
export function outcomeEntry(task: TaskKey, outcome: string): PolicyEntry | null {
  return OUTCOME_CATALOGS[task][outcome] ?? null
}

/** Catalog entry of a WorkItem reason (AP reason, AR cash residual type). */
export function reasonEntry(task: TaskKey, reason: string): PolicyEntry | null {
  return REASON_CATALOGS[task]?.[reason] ?? null
}

// ---------------------------------------------------------------- Accounts
export const KEY_ACCOUNTS: Record<string, string> = {
  '40000000': 'Proveedores',
  '40000900': 'Retención de garantía de obra (proveedores)',
  '40090000': 'GR/IR · facturas pendientes de recibir',
  '40300000': 'Proveedores del grupo',
  '40700000': 'Anticipos a proveedores',
  '41000000': 'Acreedores por servicios',
  '43000000': 'Clientes',
  '43000900': 'Retención de garantía (clientes)',
  '43090000': 'Obra ejecutada pendiente de certificar',
  '43100000': 'Pagarés en cartera',
  '43600000': 'Clientes de dudoso cobro',
  '43800000': 'Anticipos de clientes',
  '47200000': 'IVA soportado',
  '47210000': 'IVA soportado ISP (autorrepercutido)',
  '47510000': 'Retenciones IRPF practicadas',
  '47700000': 'IVA repercutido',
  '47710000': 'IVA repercutido ISP (autorrepercutido)',
  '48000000': 'Gastos anticipados',
  '49000000': 'Deterioro de clientes',
  '55200000': 'Cuenta corriente grupo (cash pooling)',
  '55300000': 'Cuenta corriente con el factor',
  '55500000': 'Cobros pendientes de aplicar',
}

const chartIndex = new WeakMap<readonly ChartAccount[], Map<string, ChartAccount>>()

function chartMap(chart: readonly ChartAccount[]): Map<string, ChartAccount> {
  let map = chartIndex.get(chart)
  if (!map) {
    map = new Map(chart.map((a) => [a.account, a]))
    chartIndex.set(chart, map)
  }
  return map
}

/** Short Spanish label of an account: key accounts first, then chart_of_accounts. */
export function accountLabel(account: string, chart?: readonly ChartAccount[] | null): string {
  const key = KEY_ACCOUNTS[account]
  if (key) return key
  const fromChart = chart ? chartMap(chart).get(account)?.description : undefined
  if (fromChart) return fromChart
  if (account.startsWith('572')) return 'Bancos c/c'
  return `Cuenta ${account}`
}
