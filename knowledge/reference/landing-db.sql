-- =====================================================================
-- Kalmora · base de llegada (landing) · datos crudos-normalizados
-- Motor: SQLite >= 3.37 (tablas STRICT). Un fichero por fase:
--   build/<phase>/landing.sqlite   (phase_dev | phase_test)
--
-- Alcance: lo que dicen las fuentes, tipado y normalizado. NADA de análisis
-- contable: no se clasifica el tipo de documento AP, no se resuelve NIF →
-- proveedor, no se casa banco↔libro, no se decide POST/HOLD/REJECT.
--
-- Convenciones
--   *_cents    INTEGER  importe en céntimos de la moneda indicada, con signo
--   *_milli    INTEGER  cantidad en milésimas
--   *_bp       INTEGER  porcentaje en puntos básicos (2100 = 21 %)
--   *_e4/_e6   INTEGER  valor escalado ×10^4 / ×10^6 (precios unitarios, tipos de cambio)
--   *_raw      TEXT     valor tal como aparece en la fuente (evidencia)
--   fechas     TEXT     ISO-8601 'YYYY-MM-DD' (o 'YYYY-MM-DDTHH:MM:SS')
--   ids        TEXT     siempre texto (ceros a la izquierda: '0007350', '04888')
--   file_id + locator   procedencia de cada fila (línea JSONL, registro N43,
--                       XPath, 'p1:l14', fila CSV)
-- golden/ queda fuera: es referencia de evaluación, no entrada.
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- 0 · Procedencia y control de carga
-- ---------------------------------------------------------------------
CREATE TABLE load_run (
  run_id          INTEGER PRIMARY KEY,
  phase           TEXT NOT NULL CHECK (phase IN ('phase_dev','phase_test')),
  close_month     TEXT NOT NULL,                 -- '2026-07'
  root_path       TEXT NOT NULL,
  loader_version  TEXT NOT NULL,
  started_at      TEXT NOT NULL,
  finished_at     TEXT
) STRICT;

CREATE TABLE source_file (
  file_id         INTEGER PRIMARY KEY,
  run_id          INTEGER NOT NULL REFERENCES load_run(run_id),
  rel_path        TEXT NOT NULL UNIQUE,          -- relativo a la raíz de la fase
  family          TEXT NOT NULL CHECK (family IN ('ERP','INBOX_AP','INBOX_AR_BILLING','INBOX_AR_REMITTANCE','BANK','TASKS')),
  format          TEXT NOT NULL CHECK (format IN ('JSONL','JSON','N43','CAMT053','CSV_BANK_MX','CSV_FACE','FACTURAE_XML','CFDI_XML','PDF_TEXT','PDF_IMAGE','OTHER')),
  encoding        TEXT,                          -- 'utf-8' | 'latin-1' | 'ascii'
  sha256          TEXT NOT NULL,
  size_bytes      INTEGER NOT NULL,
  page_count      INTEGER,                       -- PDF
  has_text_layer  INTEGER CHECK (has_text_layer IN (0,1)),
  parser          TEXT NOT NULL,                 -- 'n43@1', 'pdfplumber+regex@1', 'tesseract-spa@1'
  status          TEXT NOT NULL CHECK (status IN ('PARSED','PARTIAL','FAILED','SKIPPED')),
  error           TEXT
) STRICT;

-- Avisos de extracción/normalización. No son motivos contables.
CREATE TABLE parse_issue (
  issue_id        INTEGER PRIMARY KEY,
  file_id         INTEGER NOT NULL REFERENCES source_file(file_id),
  locator         TEXT,
  severity        TEXT NOT NULL CHECK (severity IN ('INFO','WARN','ERROR')),
  code            TEXT NOT NULL,   -- LOCALE_AMBIGUOUS, OCR_LOW_CONFIDENCE, STAMP_OVERLAP, TOTALS_NOT_RECONCILED,
                                   -- LINE_QTY_PRICE_MISMATCH, BALANCE_CHAIN_BROKEN, TWIN_MISMATCH, UNKNOWN_FIELD...
  message         TEXT NOT NULL
) STRICT;

-- ---------------------------------------------------------------------
-- 1 · Tareas (alcance a resolver)
-- ---------------------------------------------------------------------
CREATE TABLE task_item (
  task            TEXT NOT NULL CHECK (task IN ('ap_documents','ar_billing_items','ar_receipts','bank_accounts','intercompany_pair','intercompany_account','close_step')),
  seq             INTEGER NOT NULL,
  key1            TEXT NOT NULL,   -- doc_id | billing_item | bank_line | cuenta | sociedad A | cuenta IC | paso
  key2            TEXT,            -- sociedad B en parejas IC
  file_id         INTEGER NOT NULL REFERENCES source_file(file_id),
  PRIMARY KEY (task, seq)
) STRICT;

CREATE TABLE task_close (
  close_month     TEXT PRIMARY KEY,
  file_id         INTEGER NOT NULL REFERENCES source_file(file_id)
) STRICT;

-- ---------------------------------------------------------------------
-- 2 · ERP · maestros (1:1 con erp/, arrays anidados → tablas hijas)
-- ---------------------------------------------------------------------
CREATE TABLE erp_company (
  company         TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  short_name      TEXT,
  country         TEXT NOT NULL,
  currency        TEXT NOT NULL,
  role            TEXT,
  street          TEXT, postal_code TEXT, city TEXT,
  tax_id          TEXT NOT NULL,
  vat_id          TEXT,
  tax_id_norm     TEXT NOT NULL,   -- mayúsculas, sin espacios/guiones, sin prefijo país
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

CREATE TABLE erp_company_partner (           -- socios de la UTE (companies.json y ute de IC)
  company         TEXT NOT NULL REFERENCES erp_company(company),
  partner         TEXT NOT NULL,              -- '1100' | 'EXT-HIDROCON'
  share_bp        INTEGER NOT NULL,
  partner_name    TEXT, partner_tax_id TEXT,
  PRIMARY KEY (company, partner)
) STRICT;

CREATE TABLE erp_account (
  account         TEXT PRIMARY KEY,
  description     TEXT NOT NULL,
  type            TEXT NOT NULL CHECK (type IN ('BS','PL')),
  open_items      INTEGER NOT NULL CHECK (open_items IN (0,1)),
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

-- tax_codes.json aplanado: tax_codes, withholdings y customer_deductions
CREATE TABLE erp_tax_param (
  section         TEXT NOT NULL CHECK (section IN ('TAX_CODE','WITHHOLDING','CUSTOMER_DEDUCTION')),
  code            TEXT NOT NULL,              -- S21, SISP, IRPF15, RET_GAR5...
  country         TEXT,
  kind            TEXT,                       -- input | output | reverse | exempt ...
  rate_bp         INTEGER NOT NULL,
  account         TEXT,
  model           TEXT,
  description     TEXT,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL,
  PRIMARY KEY (section, code)
) STRICT;

CREATE TABLE erp_cost_center (
  cost_center     TEXT PRIMARY KEY,
  company         TEXT NOT NULL,
  description     TEXT NOT NULL,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

CREATE TABLE erp_project (
  project         TEXT PRIMARY KEY,
  company         TEXT NOT NULL,
  name            TEXT NOT NULL,
  town            TEXT,
  kind            TEXT,
  public_works    INTEGER CHECK (public_works IN (0,1)),
  start_date      TEXT, planned_end TEXT,
  budget_cost_cents INTEGER,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

CREATE TABLE erp_project_wbs (
  wbs             TEXT PRIMARY KEY,
  project         TEXT NOT NULL REFERENCES erp_project(project),
  description     TEXT NOT NULL,
  sub_archetype   TEXT
) STRICT;

CREATE TABLE erp_vendor (
  vendor          TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  tax_id          TEXT, vat_id TEXT,
  tax_id_norm     TEXT,
  country         TEXT, currency TEXT, language TEXT,
  street TEXT, postal_code TEXT, city TEXT, region TEXT, address_country TEXT,
  email           TEXT,
  email_domain    TEXT,                       -- derivado literal: parte tras '@', minúsculas
  natural_person  INTEGER CHECK (natural_person IN (0,1)),
  archetype       TEXT,
  reconciliation_account TEXT,
  default_tax_code TEXT,
  default_gl_account TEXT,
  withholding_code TEXT,
  payment_method  TEXT,
  payment_terms_days INTEGER,
  po_required     INTEGER CHECK (po_required IN (0,1)),
  intercompany    TEXT,
  guarantee_retention_bp INTEGER,
  bank_iban_norm  TEXT, bank_account TEXT, bank_swift TEXT, bank_clabe TEXT,
  alt_payee_type  TEXT, alt_payee_name TEXT, alt_payee_iban_norm TEXT, alt_payee_from TEXT,
  created_on      TEXT,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

CREATE TABLE erp_vendor_company (
  vendor TEXT NOT NULL REFERENCES erp_vendor(vendor), company TEXT NOT NULL,
  PRIMARY KEY (vendor, company)
) STRICT;

CREATE TABLE erp_vendor_bank_history (
  vendor TEXT NOT NULL REFERENCES erp_vendor(vendor), seq INTEGER NOT NULL,
  iban_norm TEXT NOT NULL, valid_to TEXT,
  PRIMARY KEY (vendor, seq)
) STRICT;

CREATE TABLE erp_vendor_garnishment (
  vendor TEXT NOT NULL REFERENCES erp_vendor(vendor), ref TEXT NOT NULL,
  amount_cents INTEGER NOT NULL, from_date TEXT NOT NULL,
  PRIMARY KEY (vendor, ref)
) STRICT;

CREATE TABLE erp_contractor_certificate (
  reference       TEXT PRIMARY KEY,
  vendor          TEXT NOT NULL,
  issued_on       TEXT NOT NULL,
  valid_until     TEXT NOT NULL,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

CREATE TABLE erp_customer (
  customer        TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  tax_id          TEXT, tax_id_norm TEXT,
  country         TEXT, kind TEXT,           -- public | private | community | group
  street TEXT, postal_code TEXT, city TEXT, region TEXT, address_country TEXT,
  currency        TEXT,
  iban_norm       TEXT,
  dir3_oficina_contable TEXT, dir3_organo_gestor TEXT, dir3_unidad_tramitadora TEXT,
  insolvency_declared_on TEXT, insolvency_court TEXT, insolvency_proceeding TEXT,
  sepa_mandate    TEXT,
  group_company   TEXT,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

CREATE TABLE erp_sales_contract (
  contract        TEXT PRIMARY KEY,
  company         TEXT NOT NULL,
  customer        TEXT NOT NULL,
  kind            TEXT NOT NULL,              -- obra_cert | service_monthly | ppa | market ...
  name            TEXT,
  project         TEXT, cost_center TEXT,
  value_cents     INTEGER, fee_cents INTEGER,
  tax_code        TEXT,
  retention_bp    INTEGER, advance_bp INTEGER, share_bp INTEGER,
  price_mwh_cents INTEGER,
  terms_days      INTEGER,
  start_date TEXT, end_date TEXT,
  factoring       INTEGER CHECK (factoring IN (0,1)),
  mx5mill         INTEGER CHECK (mx5mill IN (0,1)),
  price_revision  INTEGER CHECK (price_revision IN (0,1)),
  penalty_prob_e4 INTEGER,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

CREATE TABLE erp_sales_contract_plant (
  contract TEXT NOT NULL REFERENCES erp_sales_contract(contract), plant TEXT NOT NULL,
  PRIMARY KEY (contract, plant)
) STRICT;

CREATE TABLE erp_bank_account (
  bank_account    TEXT PRIMARY KEY,           -- 'BIN-1000'
  company         TEXT NOT NULL,
  bank_name       TEXT NOT NULL,
  bic             TEXT,
  iban_norm       TEXT, clabe TEXT,
  gl_account      TEXT NOT NULL,
  currency        TEXT NOT NULL,
  statement_format TEXT NOT NULL,            -- n43 | camt053 | csv_mx
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

CREATE TABLE erp_bank_account_role (
  bank_account TEXT NOT NULL REFERENCES erp_bank_account(bank_account), role TEXT NOT NULL,
  PRIMARY KEY (bank_account, role)
) STRICT;

CREATE TABLE erp_fx_rate (
  rate_date       TEXT NOT NULL,
  base            TEXT NOT NULL,
  currency        TEXT NOT NULL,
  rate_raw        TEXT NOT NULL,             -- '1.0667' (el JSON trae float: se conserva su repr)
  rate_e6         INTEGER NOT NULL,          -- 1066700
  source          TEXT,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL,
  PRIMARY KEY (rate_date, base, currency)
) STRICT;

-- intercompany_agreements.json
CREATE TABLE erp_ic_management_fee (
  receiver        TEXT NOT NULL,
  year            INTEGER NOT NULL,
  issuer          TEXT NOT NULL,
  monthly_cents   INTEGER NOT NULL,
  basis           TEXT,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL,
  PRIMARY KEY (receiver, year)
) STRICT;

CREATE TABLE erp_ic_loan (
  loan_id TEXT PRIMARY KEY, lender TEXT NOT NULL, borrower TEXT NOT NULL,
  principal_cents INTEGER NOT NULL, rate_bp INTEGER NOT NULL, day_count TEXT NOT NULL,
  start_date TEXT NOT NULL, note TEXT,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

CREATE TABLE erp_ic_cash_pool (
  header_account  TEXT NOT NULL,
  participant_account TEXT NOT NULL,
  scheme TEXT, interest_terms TEXT,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL,
  PRIMARY KEY (header_account, participant_account)
) STRICT;

-- ---------------------------------------------------------------------
-- 3 · ERP · registrado (diario, partidas, compras, ventas, tesorería)
-- ---------------------------------------------------------------------
CREATE TABLE erp_journal_entry (
  je_id           TEXT PRIMARY KEY,           -- '1100-2024-5000000006'
  company         TEXT NOT NULL,
  doc_type        TEXT NOT NULL,
  posting_date    TEXT NOT NULL,
  document_date   TEXT,
  reference       TEXT,
  header_text     TEXT,
  source          TEXT,                       -- MM, N43AUTO, POOL, CLOSE_ACCRUAL:reversal...
  currency        TEXT NOT NULL,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

CREATE TABLE erp_journal_line (
  je_id           TEXT NOT NULL REFERENCES erp_journal_entry(je_id),
  line            INTEGER NOT NULL,
  line_ref        TEXT NOT NULL UNIQUE,       -- '<je_id>#<line>' (clave de casación)
  account         TEXT NOT NULL,
  debit_cents     INTEGER NOT NULL,
  credit_cents    INTEGER NOT NULL,
  currency        TEXT NOT NULL,
  amount_doc_cents INTEGER,
  partner         TEXT, cost_center TEXT, wbs TEXT, tax_code TEXT,
  assignment      TEXT,
  text            TEXT,
  PRIMARY KEY (je_id, line)
) STRICT;
CREATE INDEX ix_jl_account    ON erp_journal_line(account);
CREATE INDEX ix_jl_assignment ON erp_journal_line(assignment);
CREATE INDEX ix_jl_partner    ON erp_journal_line(partner);

CREATE TABLE erp_open_item (
  open_item_id    INTEGER PRIMARY KEY,
  company TEXT NOT NULL, account TEXT NOT NULL, partner TEXT, assignment TEXT,
  balance_cents   INTEGER NOT NULL,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;
CREATE INDEX ix_oi ON erp_open_item(company, account, partner, assignment);

CREATE TABLE erp_purchase_order (
  po TEXT PRIMARY KEY, company TEXT NOT NULL, vendor TEXT NOT NULL,
  created_on TEXT, type TEXT, currency TEXT NOT NULL, project TEXT,
  purchasing_group TEXT, requester TEXT, text TEXT,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

CREATE TABLE erp_po_item (
  po TEXT NOT NULL REFERENCES erp_purchase_order(po), item INTEGER NOT NULL,
  material TEXT, description TEXT, uom TEXT,
  quantity_milli  INTEGER NOT NULL,
  unit_price_cents INTEGER NOT NULL,
  gl_account TEXT, wbs TEXT, cost_center TEXT, tax_code TEXT, asset TEXT,
  PRIMARY KEY (po, item)
) STRICT;

CREATE TABLE erp_goods_receipt (
  gr_id TEXT PRIMARY KEY, type TEXT NOT NULL, company TEXT NOT NULL,
  po TEXT NOT NULL, po_item INTEGER NOT NULL, vendor TEXT NOT NULL,
  posting_date TEXT NOT NULL,
  quantity_milli INTEGER NOT NULL, amount_cents INTEGER NOT NULL,
  reference TEXT,                              -- albarán / hoja de servicio
  je_id TEXT,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;
CREATE INDEX ix_gr_po  ON erp_goods_receipt(po, po_item);
CREATE INDEX ix_gr_ref ON erp_goods_receipt(reference);

CREATE TABLE erp_ap_invoice (
  doc_id TEXT PRIMARY KEY, company TEXT NOT NULL, vendor TEXT NOT NULL,
  kind TEXT, number TEXT, number_norm TEXT,
  issue_date TEXT, received_on TEXT, posted_on TEXT, due_date TEXT,
  je_id TEXT, currency TEXT NOT NULL,
  net_cents INTEGER, tax_cents INTEGER, gross_cents INTEGER,
  withholding_cents INTEGER, retention_cents INTEGER, payable_cents INTEGER,
  decision TEXT,
  payee_type TEXT, payee_name TEXT, payee_iban_norm TEXT, payee_ref TEXT, payee_limit_cents INTEGER,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

CREATE TABLE erp_ap_invoice_po_ref (doc_id TEXT NOT NULL REFERENCES erp_ap_invoice(doc_id), po TEXT NOT NULL, PRIMARY KEY (doc_id, po)) STRICT;
CREATE TABLE erp_ap_invoice_case   (doc_id TEXT NOT NULL REFERENCES erp_ap_invoice(doc_id), code TEXT NOT NULL, PRIMARY KEY (doc_id, code)) STRICT;

CREATE TABLE erp_ap_document_log (
  doc_id TEXT PRIMARY KEY, received_on TEXT, kind TEXT, vendor TEXT, company TEXT,
  number TEXT, number_norm TEXT, decision TEXT,
  duplicate_of TEXT, corrected_by TEXT, je_id TEXT, resolved_on TEXT,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;
CREATE TABLE erp_ap_document_log_reason (doc_id TEXT NOT NULL REFERENCES erp_ap_document_log(doc_id), code TEXT NOT NULL, PRIMARY KEY (doc_id, code)) STRICT;

CREATE TABLE erp_ar_invoice (
  invoice TEXT PRIMARY KEY, company TEXT NOT NULL, customer TEXT NOT NULL, contract TEXT,
  kind TEXT, invoice_date TEXT NOT NULL, due_date TEXT, tax_code TEXT,
  net_cents INTEGER, tax_cents INTEGER, gross_cents INTEGER,
  retention_cents INTEGER, payable_cents INTEGER, currency TEXT NOT NULL,
  factored INTEGER CHECK (factored IN (0,1)),
  je_id TEXT, certification TEXT,
  face_oficina_contable TEXT, face_organo_gestor TEXT, face_unidad_tramitadora TEXT, face_registry TEXT,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

CREATE TABLE erp_ar_invoice_deduction (
  invoice TEXT NOT NULL REFERENCES erp_ar_invoice(invoice), seq INTEGER NOT NULL,
  code TEXT NOT NULL, amount_cents INTEGER NOT NULL, account TEXT,
  PRIMARY KEY (invoice, seq)
) STRICT;

-- billing_history.jsonl: cabecera con columnas por tipo + líneas tipadas.
-- La misma forma se usa para lo extraído de inbox/ar/billing (§5).
CREATE TABLE erp_billing_history (
  billing_id TEXT PRIMARY KEY, type TEXT NOT NULL, company TEXT NOT NULL,
  contract TEXT, customer TEXT, month TEXT NOT NULL,
  -- OBRA_CERTIFICATION
  cert_id TEXT, cert_project TEXT, cert_number INTEGER, cert_month TEXT,
  cert_cumulative_cents INTEGER, cert_previous_cents INTEGER, cert_current_cents INTEGER,
  cert_approved INTEGER, cert_approved_on TEXT, cert_approver TEXT,
  -- SERVICE_MONTHLY
  fee_cents INTEGER,
  -- PPA / MARKET_SETTLEMENT
  period TEXT, share_bp INTEGER, price_mwh_e4 INTEGER, avg_price_e4 INTEGER, deviations_cents INTEGER,
  -- PRICE_REVISION
  rev_decree TEXT, rev_old_fee_cents INTEGER, rev_new_fee_cents INTEGER, rev_effective TEXT, rev_approved_on TEXT,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

CREATE TABLE erp_billing_history_line (
  billing_id TEXT NOT NULL REFERENCES erp_billing_history(billing_id), seq INTEGER NOT NULL,
  line_kind TEXT NOT NULL CHECK (line_kind IN ('CERT_CHAPTER','EXTRA_SERVICE','PRODUCTION_PLANT','SETTLEMENT_PLANT','REVISION_MONTH')),
  ref TEXT,                 -- orden de servicio | planta | mes revisado
  description TEXT,
  amount_cents INTEGER, mwh_milli INTEGER,
  approved INTEGER, account TEXT, wbs TEXT,
  PRIMARY KEY (billing_id, seq)
) STRICT;

CREATE TABLE erp_promissory_note (
  note_number TEXT PRIMARY KEY, customer TEXT NOT NULL, company TEXT NOT NULL,
  received_on TEXT, maturity TEXT, amount_cents INTEGER NOT NULL, bank_name TEXT, je_id TEXT,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;
CREATE TABLE erp_promissory_note_application (
  note_number TEXT NOT NULL REFERENCES erp_promissory_note(note_number), invoice TEXT NOT NULL,
  amount_cents INTEGER NOT NULL, PRIMARY KEY (note_number, invoice)
) STRICT;

CREATE TABLE erp_factoring_assignment (
  invoice TEXT PRIMARY KEY, remittance TEXT, assigned_on TEXT, customer TEXT,
  advance_cents INTEGER, interest_cents INTEGER, fee_cents INTEGER,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;

CREATE TABLE erp_sepa_remittance (
  remittance TEXT PRIMARY KEY, remittance_date TEXT NOT NULL, total_cents INTEGER NOT NULL,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL
) STRICT;
CREATE TABLE erp_sepa_remittance_invoice (
  remittance TEXT NOT NULL REFERENCES erp_sepa_remittance(remittance), invoice TEXT NOT NULL,
  PRIMARY KEY (remittance, invoice)
) STRICT;

CREATE TABLE erp_penalty_notice (
  invoice TEXT NOT NULL, contract TEXT, customer TEXT,
  amount_cents INTEGER NOT NULL, notified_on TEXT NOT NULL, resolution TEXT,
  file_id INTEGER NOT NULL REFERENCES source_file(file_id), locator TEXT NOT NULL,
  PRIMARY KEY (invoice, notified_on)
) STRICT;

-- ---------------------------------------------------------------------
-- 4 · Banco (N43, camt.053, CSV MX) + gemelo .lines.jsonl
-- ---------------------------------------------------------------------
CREATE TABLE bank_statement (
  statement_id    INTEGER PRIMARY KEY,
  bank_account    TEXT NOT NULL,               -- carpeta: 'BIN-1000'
  period          TEXT NOT NULL,               -- '2026-07'
  format          TEXT NOT NULL CHECK (format IN ('N43','CAMT053','CSV_BANK_MX')),
  account_id_raw  TEXT,                        -- N43 entidad+oficina+DC+cuenta | IBAN | 'Cuenta' CSV
  currency        TEXT NOT NULL,
  date_from TEXT, date_to TEXT,
  opening_cents   INTEGER NOT NULL,
  closing_cents   INTEGER NOT NULL,            -- del registro 33 / CLBD / último Saldo
  debit_count INTEGER, debit_total_cents INTEGER, credit_count INTEGER, credit_total_cents INTEGER,
  chain_ok        INTEGER NOT NULL CHECK (chain_ok IN (0,1)),   -- opening + Σ = closing
  twin_ok         INTEGER NOT NULL CHECK (twin_ok IN (0,1)),    -- coincide con .lines.jsonl
  file_id         INTEGER NOT NULL REFERENCES source_file(file_id),
  twin_file_id    INTEGER NOT NULL REFERENCES source_file(file_id),
  UNIQUE (bank_account, period)
) STRICT;

CREATE TABLE bank_line (
  bank_line       TEXT PRIMARY KEY,            -- 'BL0005631' (del gemelo / NtryRef)
  statement_id    INTEGER NOT NULL REFERENCES bank_statement(statement_id),
  seq             INTEGER NOT NULL,            -- orden dentro del extracto
  booking_date    TEXT NOT NULL,
  value_date      TEXT,
  amount_cents    INTEGER NOT NULL,            -- abono +, cargo −
  currency        TEXT NOT NULL,
  text_twin       TEXT,                        -- 'text' del .lines.jsonl (normalizado/truncado)
  text_full       TEXT,                        -- concepto completo del original (23 concatenados | Ustrd | Concepto)
  -- N43 registro 22
  n43_branch TEXT, n43_common_concept TEXT, n43_own_concept TEXT,
  n43_doc_number TEXT, n43_ref1 TEXT, n43_ref2 TEXT,
  -- N43 registro 24 (equivalencia de divisa)
  orig_currency TEXT, orig_amount_cents INTEGER,
  -- camt.053
  camt_bank_tx_code TEXT, camt_end_to_end_id TEXT, camt_status TEXT,
  counterparty_name TEXT,                      -- Dbtr/Cdtr Nm
  -- CSV MX
  csv_reference TEXT, csv_tracking_key TEXT,   -- 'Clave de rastreo'
  running_balance_cents INTEGER,               -- 'Saldo' CSV
  locator         TEXT NOT NULL,
  UNIQUE (statement_id, seq)
) STRICT;
CREATE INDEX ix_bl_date ON bank_line(booking_date);

CREATE TABLE bank_line_text (                  -- N43 registros 23 (1..n por movimiento)
  bank_line TEXT NOT NULL REFERENCES bank_line(bank_line), seq INTEGER NOT NULL,
  data_code TEXT, text TEXT NOT NULL,
  PRIMARY KEY (bank_line, seq)
) STRICT;

-- ---------------------------------------------------------------------
-- 5 · Bandejas: mensajes, adjuntos y documentos extraídos
-- ---------------------------------------------------------------------
CREATE TABLE ap_message (
  doc_id          TEXT PRIMARY KEY,            -- 'API004204'
  channel         TEXT NOT NULL CHECK (channel IN ('email','portal','facturae','cfdi','paper')),
  received_at     TEXT NOT NULL,
  mailbox         TEXT,
  from_addr TEXT, from_domain TEXT, to_addr TEXT, subject TEXT, body TEXT,
  source TEXT, uploaded_by TEXT, uploaded_by_domain TEXT,
  file_id         INTEGER NOT NULL REFERENCES source_file(file_id)
) STRICT;

CREATE TABLE ap_attachment (
  doc_id          TEXT NOT NULL REFERENCES ap_message(doc_id),
  seq             INTEGER NOT NULL,
  filename        TEXT NOT NULL,
  filename_prefix TEXT,                        -- factura | invoice | facturae | proforma | statement | letter_cession | letter_bank_change | certificate_art43 | <uuid>
  file_id         INTEGER REFERENCES source_file(file_id),   -- NULL si el adjunto declarado no existe
  PRIMARY KEY (doc_id, seq)
) STRICT;

CREATE TABLE ar_billing_item (
  billing_item    TEXT PRIMARY KEY,
  type            TEXT NOT NULL,               -- OBRA_CERTIFICATION | SERVICE_MONTHLY | PRICE_REVISION | PPA | MARKET_SETTLEMENT
  company TEXT NOT NULL, contract TEXT, customer TEXT, month TEXT NOT NULL,
  file_id         INTEGER NOT NULL REFERENCES source_file(file_id)
) STRICT;

CREATE TABLE ar_billing_item_document (
  billing_item TEXT NOT NULL REFERENCES ar_billing_item(billing_item), seq INTEGER NOT NULL,
  filename TEXT NOT NULL, file_id INTEGER REFERENCES source_file(file_id),
  PRIMARY KEY (billing_item, seq)
) STRICT;

-- Texto bruto por página: base de toda extracción y de la evidencia.
CREATE TABLE doc_page_text (
  file_id         INTEGER NOT NULL REFERENCES source_file(file_id),
  page            INTEGER NOT NULL,
  method          TEXT NOT NULL CHECK (method IN ('PDF_TEXT','OCR','XML')),
  text            TEXT NOT NULL,
  ocr_mean_conf   INTEGER,                     -- 0..100
  PRIMARY KEY (file_id, page)
) STRICT;

-- Documento comercial extraído (facturas AP de cualquier formato, cartas, extractos,
-- proformas, certificados, avisos de pago). Lo que el documento DICE, no lo que ES.
CREATE TABLE doc_extract (
  extract_id      INTEGER PRIMARY KEY,
  file_id         INTEGER NOT NULL UNIQUE REFERENCES source_file(file_id),
  doc_id          TEXT REFERENCES ap_message(doc_id),            -- NULL fuera de la bandeja AP
  method          TEXT NOT NULL CHECK (method IN ('FACTURAE_XML','CFDI_XML','PDF_TEXT','PDF_OCR')),
  title_raw       TEXT,                        -- 'FACTURA', 'FATURA', 'NOTA DE CRÉDITO', 'EXTRACTO DE CUENTA'...
  language        TEXT,                        -- es | pt | en
  number_locale   TEXT CHECK (number_locale IN ('ES','EN','MIXED')),
  issuer_name TEXT, issuer_tax_id_raw TEXT, issuer_tax_id_norm TEXT, issuer_address TEXT,
  recipient_name TEXT, recipient_tax_id_raw TEXT, recipient_tax_id_norm TEXT, recipient_address TEXT,
  doc_number_raw  TEXT,
  doc_number_norm TEXT,                        -- mayúsculas, solo [A-Z0-9]; quitar prefijos es análisis
  series          TEXT,
  issue_date TEXT, due_date TEXT, period_start TEXT, period_end TEXT,
  currency        TEXT,
  net_cents INTEGER, tax_cents INTEGER, gross_cents INTEGER,
  withholding_cents INTEGER, retention_cents INTEGER, payable_cents INTEGER,   -- tal como figuran
  payment_terms_raw TEXT,
  iban_norm       TEXT,                        -- IBAN de cobro impreso
  legal_notes     TEXT,                        -- leyendas ISP, REAV, 'sin validez fiscal'...
  stamp_text      TEXT,                        -- CONFORME / Recibido / TOMA DE RAZÓN detectados
  -- específicos de formato
  facturae_class TEXT, facturae_doc_type TEXT, facturae_batch_id TEXT,
  cfdi_uuid TEXT, cfdi_type TEXT, cfdi_payment_method TEXT, cfdi_payment_form TEXT, cfdi_use TEXT,
  -- control de calidad de la extracción (no decisión contable)
  qc_lines_sum_ok INTEGER, qc_totals_ok INTEGER, qc_line_math_ok INTEGER
) STRICT;
CREATE INDEX ix_dx_doc     ON doc_extract(doc_id);
CREATE INDEX ix_dx_issuer  ON doc_extract(issuer_tax_id_norm, doc_number_norm);

CREATE TABLE doc_extract_line (
  extract_id      INTEGER NOT NULL REFERENCES doc_extract(extract_id),
  line_no         INTEGER NOT NULL,
  page            INTEGER,
  product_code    TEXT,                        -- código / ClaveProdServ
  description     TEXT NOT NULL,
  delivery_ref    TEXT,                        -- 'AL-086310' | 'REM-006926' (literal)
  delivery_date   TEXT,                        -- '(09/06)' + año del documento
  quantity_milli  INTEGER,
  uom             TEXT,
  unit_price_raw  TEXT,
  unit_price_e4   INTEGER,                     -- ×10^4 de la moneda
  amount_cents    INTEGER,
  tax_rate_bp     INTEGER,                     -- si la línea lo indica (Facturae/CFDI)
  po_ref          TEXT,                        -- 'Su pedido' / IssuerTransactionReference
  raw_line        TEXT,
  PRIMARY KEY (extract_id, line_no)
) STRICT;

CREATE TABLE doc_extract_tax (                 -- cuadro de impuestos y retenciones impreso
  extract_id      INTEGER NOT NULL REFERENCES doc_extract(extract_id),
  seq             INTEGER NOT NULL,
  kind            TEXT NOT NULL CHECK (kind IN ('OUTPUT_TAX','WITHHOLDING','GUARANTEE_RETENTION','OTHER')),
  label_raw       TEXT,                        -- 'IVA 21%', 'Retenção IRS 25%', 'Retención de garantía', TaxTypeCode
  rate_bp         INTEGER,
  base_cents      INTEGER,
  amount_cents    INTEGER,
  PRIMARY KEY (extract_id, seq)
) STRICT;

CREATE TABLE doc_extract_ref (                 -- referencias citadas por el documento
  extract_id      INTEGER NOT NULL REFERENCES doc_extract(extract_id),
  ref_type        TEXT NOT NULL CHECK (ref_type IN ('PO','DELIVERY','CORRECTED_INVOICE','LISTED_INVOICE','CONTRACT','CERTIFICATE','IBAN_NEW','IBAN_OLD','IBAN_ASSIGNEE','PAYMENT_ORDER','OTHER')),
  ref_value       TEXT NOT NULL,
  amount_cents    INTEGER,                     -- p. ej. factura listada en extracto o aviso
  ref_date        TEXT,
  status_raw      TEXT,                        -- 'Cobrada', 'Vencida', 'Pendiente'
  locator         TEXT,
  PRIMARY KEY (extract_id, ref_type, ref_value)
) STRICT;

-- Evidencia campo a campo: valor bruto, normalizado, dónde y con qué confianza.
CREATE TABLE doc_field_evidence (
  extract_id      INTEGER NOT NULL REFERENCES doc_extract(extract_id),
  field           TEXT NOT NULL,               -- 'issue_date', 'gross_cents', 'recipient_tax_id_norm'...
  raw_value       TEXT,
  norm_value      TEXT,
  page            INTEGER,
  locator         TEXT,                        -- 'p1:l3' | XPath | atributo CFDI
  confidence      INTEGER,                     -- 0..100 (100 en XML)
  PRIMARY KEY (extract_id, field)
) STRICT;

-- Documentos de inbox/ar/billing: misma forma que erp_billing_history.
CREATE TABLE ar_billing_extract (
  billing_item    TEXT PRIMARY KEY REFERENCES ar_billing_item(billing_item),
  file_id         INTEGER NOT NULL REFERENCES source_file(file_id),
  title_raw       TEXT,                        -- 'CERTIFICACIÓN DE OBRA Nº 10', 'ESTIMACIÓN...', 'Decreto...'
  currency        TEXT,
  cert_number INTEGER, cert_month TEXT,
  cert_cumulative_cents INTEGER, cert_previous_cents INTEGER, cert_current_cents INTEGER,
  approval_stamp_raw TEXT,                     -- 'CONFORME' | 'PENDIENTE…' | NULL
  approver_raw TEXT, approval_date TEXT,
  fee_cents INTEGER,
  period TEXT, share_bp INTEGER, price_mwh_e4 INTEGER, avg_price_e4 INTEGER, deviations_cents INTEGER,
  rev_decree TEXT, rev_old_fee_cents INTEGER, rev_new_fee_cents INTEGER, rev_effective TEXT, rev_approved_on TEXT,
  notes_raw TEXT,
  qc_sum_ok INTEGER
) STRICT;

CREATE TABLE ar_billing_extract_line (
  billing_item TEXT NOT NULL REFERENCES ar_billing_extract(billing_item), seq INTEGER NOT NULL,
  line_kind TEXT NOT NULL CHECK (line_kind IN ('CERT_CHAPTER','FEE','EXTRA_SERVICE','PRODUCTION_PLANT','SETTLEMENT_PLANT','REVISION_MONTH')),
  ref TEXT, description TEXT,
  amount_cents INTEGER, mwh_milli INTEGER,
  status_raw TEXT,                             -- conformidad de extraordinarios
  raw_line TEXT,
  PRIMARY KEY (billing_item, seq)
) STRICT;

-- inbox/ar/remittances
CREATE TABLE remittance_advice (
  advice_id       TEXT PRIMARY KEY,            -- 'RCPT-000520'
  payer_name_meta TEXT,                        -- from_ del .json
  channel         TEXT,
  received_at     TEXT,
  meta_file_id    INTEGER REFERENCES source_file(file_id),
  pdf_extract_id  INTEGER REFERENCES doc_extract(extract_id)    -- cabecera y facturas en doc_extract / doc_extract_ref
) STRICT;

CREATE TABLE face_invoice_status (
  file_id         INTEGER NOT NULL REFERENCES source_file(file_id),
  row_no          INTEGER NOT NULL,
  customer        TEXT,                        -- del nombre de fichero: FACe_estado_facturas_<C>_<YYYYMM>
  file_month      TEXT,
  registry_number TEXT,
  invoice_number  TEXT NOT NULL,
  invoice_date    TEXT,
  amount_cents    INTEGER,
  status          TEXT,
  status_date     TEXT,
  paid_cents      INTEGER,
  PRIMARY KEY (file_id, row_no)
) STRICT;
