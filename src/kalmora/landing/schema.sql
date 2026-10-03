-- =====================================================================
-- Kalmora · capa de llegada «tal como dice la fuente»
-- Motor: DuckDB >= 1.1. Un fichero por fase: build/<phase>/landing.duckdb
--
-- 8 tablas + adaptadores exactos de solo lectura sobre erp/.
--
-- Qué hace: parsear, tipar y normalizar el FORMATO (céntimos, ISO, NIF,
-- IBAN), conservar lo que dice cada fichero por separado y su evidencia.
-- Qué NO hace: clasificar documentos, resolver NIF → sociedad/proveedor,
-- elegir entre valores en conflicto, casar banco↔libro ni aplicar reglas
-- de POLITICAS_CONTABLES.md. Eso es la capa de análisis (ver ap_case en
-- landing-db.html).
--
-- Convenciones
--   *_cents  BIGINT   céntimos con signo, en la moneda de la fila
--   *_milli  BIGINT   milésimas de cantidad
--   *_bp     INTEGER  puntos básicos (2100 = 21 %)
--   *_e4     BIGINT   ×10^4 (precios unitarios, €/MWh)
--   *_raw    VARCHAR  literal de la fuente
--   *_norm   VARCHAR  identificador canónico
--   ids      VARCHAR  siempre texto (ceros a la izquierda)
--   extra / evidence JSON  lo específico de un formato y la evidencia por campo;
--            todo valor que use una regla contable va en columna tipada, no en JSON.
-- golden/ queda fuera.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1 · source_file — inventario y procedencia de todo el árbol
-- ---------------------------------------------------------------------
CREATE TABLE source_file (
  file_id         INTEGER PRIMARY KEY,
  phase           VARCHAR NOT NULL ,
  rel_path        VARCHAR NOT NULL UNIQUE,
  family          VARCHAR NOT NULL CHECK (family IN ('ERP','INBOX_AP','INBOX_AR_BILLING','INBOX_AR_REMITTANCE','INBOX_AR_NOTICE','BANK','TASKS')),
  format          VARCHAR NOT NULL CHECK (format IN ('JSONL','JSON','N43','CAMT053','CSV_BANK_MX','CSV_FACE','FACTURAE_XML','CFDI_XML','PDF_TEXT','PDF_IMAGE','PDF','OTHER')),
  encoding        VARCHAR,
  sha256          VARCHAR,                   -- NULL only when source bytes could not be read
  size_bytes      BIGINT,
  page_count      INTEGER,
  parser          VARCHAR NOT NULL,          -- 'n43@1', 'pdfplumber+regex@1', 'tesseract-spa@1', 'erp-view'
  status          VARCHAR NOT NULL CHECK (status IN ('PARSED','PARTIAL','FAILED','SKIPPED')),
  error           VARCHAR,
  loaded_at       TIMESTAMP NOT NULL
);

-- ---------------------------------------------------------------------
-- 2 · parse_issue — avisos de extracción (no son motivos contables)
-- ---------------------------------------------------------------------
CREATE TABLE parse_issue (
  issue_id        INTEGER PRIMARY KEY,
  file_id         INTEGER NOT NULL REFERENCES source_file(file_id),
  locator         VARCHAR,
  severity        VARCHAR NOT NULL CHECK (severity IN ('INFO','WARN','ERROR')),
  code            VARCHAR NOT NULL,           -- OCR_LOW_CONFIDENCE, LOCALE_AMBIGUOUS, STAMP_OVERLAP,
                                              -- TOTALS_NOT_RECONCILED, LINE_MATH, BALANCE_CHAIN_BROKEN,
                                              -- TWIN_MISMATCH, ATTACHMENT_MISSING, UNKNOWN_LAYOUT
  message         VARCHAR NOT NULL
);

-- ---------------------------------------------------------------------
-- 3 · task_item — alcance (tasks/*.json)
-- ---------------------------------------------------------------------
CREATE TABLE task_item (
  task            VARCHAR NOT NULL CHECK (task IN ('ap_documents','ar_billing_items','ar_receipts','bank_accounts','intercompany_pair','intercompany_account','close_step')),
  seq             INTEGER NOT NULL,
  key1            VARCHAR NOT NULL,           -- doc_id | billing_item | bank_line | cuenta | sociedad A | cuenta IC | paso
  key2            VARCHAR,                    -- sociedad B (parejas IC) | mes de cierre (close_step)
  file_id         INTEGER NOT NULL REFERENCES source_file(file_id),
  PRIMARY KEY (task, seq)
);

-- ---------------------------------------------------------------------
-- 4 · bank_statement — un extracto por cuenta y mes (N43 | camt.053 | CSV MX)
-- ---------------------------------------------------------------------
CREATE TABLE bank_statement (
  statement_id    INTEGER PRIMARY KEY,
  bank_account    VARCHAR NOT NULL,           -- carpeta: 'BIN-1000'
  period          VARCHAR NOT NULL,           -- '2026-07'
  format          VARCHAR NOT NULL CHECK (format IN ('N43','CAMT053','CSV_BANK_MX')),
  account_id_raw  VARCHAR,                    -- entidad+oficina+DC+cuenta | IBAN | 'Cuenta'
  currency        VARCHAR NOT NULL,
  date_from       DATE,
  date_to         DATE,
  opening_cents   BIGINT NOT NULL,
  closing_cents   BIGINT NOT NULL,
  chain_ok        BOOLEAN NOT NULL,           -- opening + Σ líneas = closing
  twin_ok         BOOLEAN NOT NULL,           -- orden e importes = .lines.jsonl
  file_id         INTEGER NOT NULL REFERENCES source_file(file_id),
  twin_file_id    INTEGER NOT NULL REFERENCES source_file(file_id),
  UNIQUE (bank_account, period)
);

-- ---------------------------------------------------------------------
-- 5 · bank_line — movimiento, mismo formato para los tres orígenes
-- ---------------------------------------------------------------------
CREATE TABLE bank_line (
  bank_line       VARCHAR PRIMARY KEY,        -- 'BL0005631' (gemelo .lines.jsonl / NtryRef)
  statement_id    INTEGER NOT NULL REFERENCES bank_statement(statement_id),
  seq             INTEGER NOT NULL,
  booking_date    DATE NOT NULL,
  value_date      DATE,
  amount_cents    BIGINT NOT NULL,            -- abono +, cargo −
  currency        VARCHAR NOT NULL,
  text_twin       VARCHAR,                    -- 'text' del gemelo (normalizado/truncado)
  text_full       VARCHAR,                    -- concepto completo: registros 23 | Ustrd | Concepto
  counterparty    VARCHAR,                    -- Dbtr/Cdtr Nm (camt) cuando existe
  reference       VARCHAR,                    -- ref1/ref2 N43 | EndToEndId | Referencia CSV
  orig_currency   VARCHAR,                    -- N43 registro 24
  orig_amount_cents BIGINT,
  extra           JSON,                       -- n43: conceptos común/propio, nº doc, ref1, ref2, registros 23
                                              -- camt: BkTxCd, Sts; csv: clave de rastreo, saldo
  locator         VARCHAR NOT NULL,
  UNIQUE (statement_id, seq)
);

-- ---------------------------------------------------------------------
-- 6 · inbound_item — lo que entra por las bandejas (un registro por caso recibido)
-- ---------------------------------------------------------------------
CREATE TABLE inbound_item (
  item_id         VARCHAR PRIMARY KEY,        -- 'API004204' | 'BILL-CT-1200-AL01-202607' | 'RCPT-000520' | 'FACE-C200001-202607'
  kind            VARCHAR NOT NULL CHECK (kind IN ('AP_MESSAGE','AR_BILLING_ITEM','REMITTANCE_ADVICE','FACE_EXPORT','AR_NOTICE')),
  received_at     TIMESTAMP,
  channel         VARCHAR,                    -- email | portal | facturae | cfdi | paper | pdf
  -- AP
  sender_addr     VARCHAR,                    -- from | uploaded_by
  sender_domain   VARCHAR,
  subject         VARCHAR,
  body            VARCHAR,
  -- AR
  billing_type    VARCHAR,                    -- OBRA_CERTIFICATION | SERVICE_MONTHLY | PRICE_REVISION | PPA | MARKET_SETTLEMENT
  company         VARCHAR,
  contract        VARCHAR,
  customer        VARCHAR,                    -- item.json, o del nombre del CSV FACe
  month           VARCHAR,
  payer_name      VARCHAR,                    -- aviso de pago: from_
  declared_files  VARCHAR[],                  -- attachments | documents | file
  extra           JSON,                       -- mailbox, source, to, resto de metadatos
  file_id         INTEGER REFERENCES source_file(file_id)   -- message.json | item.json | aviso.json (NULL en FACe)
);

-- ---------------------------------------------------------------------
-- 7 · document — un fichero extraído, «lo que dice», sin consolidar
--     PDF y XML de un mismo CFDI son DOS filas: compararlos es análisis.
-- ---------------------------------------------------------------------
CREATE TABLE document (
  document_id     INTEGER PRIMARY KEY,
  file_id         INTEGER NOT NULL UNIQUE REFERENCES source_file(file_id),
  item_id         VARCHAR NOT NULL REFERENCES inbound_item(item_id),
  attachment_seq  INTEGER NOT NULL,
  filename        VARCHAR NOT NULL,
  filename_prefix VARCHAR,                    -- factura | invoice | facturae | proforma | statement | letter_cession
                                              -- | letter_bank_change | certificate_art43 | documento | aviso_pago | <uuid>
  method          VARCHAR NOT NULL CHECK (method IN ('FACTURAE_XML','CFDI_XML','PDF_TEXT','PDF_OCR','CSV','FACTS','UNEXTRACTED')),
  title_raw       VARCHAR,                    -- 'FACTURA', 'NOTA DE CRÉDITO', 'CERTIFICACIÓN DE OBRA Nº 10', 'Decreto…'
  language        VARCHAR,
  number_locale   VARCHAR CHECK (number_locale IN ('ES','EN','MIXED')),
  issuer_name     VARCHAR,
  issuer_tax_id_raw  VARCHAR,
  issuer_tax_id_norm VARCHAR,
  recipient_name  VARCHAR,
  recipient_tax_id_raw  VARCHAR,
  recipient_tax_id_norm VARCHAR,
  doc_number_raw  VARCHAR,
  doc_number_norm VARCHAR,                    -- mayúsculas, solo [A-Z0-9]
  issue_date      DATE,
  due_date        DATE,
  period_start    DATE,
  period_end      DATE,
  currency        VARCHAR,
  net_cents       BIGINT,                     -- importes TAL COMO FIGURAN impresos
  tax_cents       BIGINT,
  gross_cents     BIGINT,
  withholding_cents BIGINT,
  retention_cents BIGINT,
  payable_cents   BIGINT,
  iban_norm       VARCHAR,                    -- IBAN de cobro impreso
  stamp_text      VARCHAR,                    -- 'CONFORME', 'Recibido', 'TOMA DE RAZÓN'
  legal_notes     VARCHAR,                    -- leyendas ISP, REAV, 'sin validez fiscal'
  qc_line_math_ok BOOLEAN,                    -- cantidad × precio = importe en todas las líneas
  qc_lines_sum_ok BOOLEAN,                    -- Σ líneas = base
  qc_totals_ok    BOOLEAN,                    -- base + cuotas − retenciones = total
  ocr_mean_conf   INTEGER,                    -- 0..100, solo PDF_OCR
  full_text       VARCHAR,                    -- texto extraído (PDF/OCR) para reproceso
  extra           JSON,                       -- cfdi: uuid, TipoDeComprobante, MetodoPago, UsoCFDI
                                              -- facturae: InvoiceClass, BatchIdentifier
                                              -- AR: decreto, fecha de efectos, aprobador, periodo PPA
  evidence        JSON                        -- {campo: {raw, page, locator, confidence}}
);
CREATE INDEX ix_document_item   ON document(item_id);
CREATE INDEX ix_document_number ON document(issuer_tax_id_norm, doc_number_norm);

-- ---------------------------------------------------------------------
-- 8 · document_line — todo lo que un documento enumera, tipado por kind
-- ---------------------------------------------------------------------
CREATE TABLE document_line (
  document_id     INTEGER NOT NULL REFERENCES document(document_id),
  seq             INTEGER NOT NULL,
  kind            VARCHAR NOT NULL CHECK (kind IN (
                    'ITEM',          -- línea de factura / concepto
                    'TAX',           -- cuota de IVA impresa
                    'WITHHOLDING',   -- IRPF, ISR, IVA retenido, IRS
                    'GUARANTEE',     -- retención de garantía
                    'SUMMARY',       -- importe resumen etiquetado: CUMULATIVE, PREVIOUS, CURRENT, FEE_NEW, FEE_OLD, DEVIATIONS, TOTAL_TRANSFERRED
                    'CHAPTER',       -- capítulo de certificación
                    'EXTRA_SERVICE', -- servicio extraordinario con su conformidad
                    'PLANT',         -- planta: MWh e importe
                    'MONTH',         -- mes facturable en revisión de precios
                    'REF',           -- referencia citada: label = PO | DELIVERY | CORRECTED_INVOICE | LISTED_INVOICE
                                     --   | IBAN_NEW | IBAN_OLD | IBAN_ASSIGNEE | PAYMENT_ORDER | CERTIFICATE
                    'ROW')),         -- fila de exportación FACe
  label           VARCHAR,                    -- etiqueta impresa o normalizada ('IVA 21%', 'CUMULATIVE', 'PO')
  description     VARCHAR,
  ref             VARCHAR,                    -- valor de la referencia / nº de factura / planta / mes
  po_ref          VARCHAR,                    -- ITEM: pedido citado en la línea
  delivery_ref    VARCHAR,                    -- ITEM: 'AL-086310' | 'REM-006926'
  ref_date        DATE,
  quantity_milli  BIGINT,
  uom             VARCHAR,
  unit_price_raw  VARCHAR,
  unit_price_e4   BIGINT,
  rate_bp         INTEGER,
  base_cents      BIGINT,
  amount_cents    BIGINT,
  mwh_milli       BIGINT,
  status_raw      VARCHAR,                    -- 'Cobrada', 'PAGADA', 'CONFORME', 'Pendiente de conformidad'
  page            INTEGER,
  locator         VARCHAR,
  raw_line        VARCHAR,
  PRIMARY KEY (document_id, seq)
);

-- ---------------------------------------------------------------------

CREATE TABLE landing_meta (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL);
ALTER TABLE document ADD COLUMN facts_json JSON;
ALTER TABLE document ADD COLUMN extractor_version VARCHAR;
