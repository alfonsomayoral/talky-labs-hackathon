# Direct XML facts — #39

`XMLDocumentExtractor` implements the asynchronous `DocumentExtractor` protocol
for `ParsedDocument` produced by the source router. It supports Facturae 3.2.2
with one invoice and CFDI 4.0. It performs no I/O or provider calls, and requires
no optional LLM dependency:

```python
parsed = DocumentRouter(phase_path).parse(relative_inbox_path)
raw = await XMLDocumentExtractor().extract(parsed)
normalized = normalize_document_facts(raw)
```

Each original leaf is retained as `raw.xml.<exact source_field>`. Recognized
headers, identities, lines, tax groups and Facturae installments also receive
named aliases. Every alias contains the identical source string and its original
document/path/quote. Missing leaves stay absent; empty observed leaves remain
empty. The source hash and `xml-source-extractor-v1` identify this transformation.
There is no fabricated LLM response or provider-cache record.

The extractor keeps currency, dates, quantities, prices and amounts as source
strings. #41 converts them to integer cents/milli/e4, retaining diagnostics.
Facturae `TaxRate` is a percentage; CFDI `TasaOCuota` retains its fraction literal.
Only an observed CFDI `TipoFactor=Tasa` receives a fractional rate alias; fixed
quotas, exemptions and missing factor metadata retain raw leaves without one.
Header and line tax groups, charged and withheld taxes, and different tax codes
remain separate. The extractor never selects an ERP treatment or account.

Facturae `InvoiceTotal` and CFDI `Total` are exposed as `payable`, preserving
withholding separately. They are not relabeled as gross before withholding.
Outstanding/partial payment amounts remain raw. CFDI subtotals receive a `net`
alias only when their corresponding discount is absent or explicitly zero;
nonzero/invalid discounts preserve subtotal and discount leaves without inventing
a net calculation. Facturae line `GrossAmount` is a line `amount`; general
invoice discounts and allocations remain for the arithmetic layer.

Document numbers preserve the actual InvoiceNumber/Folio. Series remain separate
and are never blindly concatenated. Type attributes remain literal
`raw.invoice_document_type`, `raw.invoice_class`, and `raw.cfdi_type`; #40 owns
their interpretation. No document type, PO, approval or master identity is
inferred from a filename, description, total or absent value.

Unsupported roots/versions, duplicate or missing XML locators and multi-invoice
Facturae batches raise `XMLExtractionError(path, code)`. The caller records this
as an extraction limitation and decides the next step explicitly. This module
does not validate XSDs, signatures or legal invoice validity.

PDF, XML and email are independent sources. Call the extractor separately for
each supported XML and retain the corresponding PDF facts independently; the
comparison layer can then detect CFDI/PDF disagreement. Folder orchestration,
PDF/OCR, residual semantic interpretation and AP task integration belong to the
existing runner and #139/#140 and are not changed here.

Validation uses eight regressions for exact evidence, normalization, tax groups,
withholding, discounts, source independence, versions and batches. With
`KALMORA_PHASE_ERP` set to the development ERP directory, the source regression
extracts and verifies all 58 original July XML attachments (43 Facturae, 15 CFDI)
against their parsed leaves without reading golden. These are attachments, not
58 completed AP tasks or a claim that all 305 tasks are resolved.
