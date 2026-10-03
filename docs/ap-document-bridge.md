# AP normalized document bridge

`kalmora.ap_document_bridge` connects normalized extraction to AP identity,
header, line and reference consumers. It does not decide eligibility, choose an
account, infer a tax regime or commit a posting. Its inputs contain original
evidence and exact normalized units; it never reads Golden or a provider.

```python
source = APSourceView.from_normalized(
    normalized,
    source_path=parsed.path,
    classification=classify_ap_source(normalized.raw),
)
task = APDocumentBridge(canonical_doc_id, (source,))
identity = catalog.resolve(
    supplier_tax_ids=task.header.issuer_tax_id.candidates,
    recipient_tax_ids=task.header.recipient_tax_id.candidates,
    expected_company=company_from_task_or_confirmed_order,
)
```

`APSourceView.from_normalized` snapshots one attachment, checks its raw and
normalized source hashes, and requires all evidence to name that attachment.
Empty facts still require an explicit source path. A runner may supply the
existing format-aware classification; the default delegates all interpretation
to `classify_document` without adding further type rules. Classification retains
literal evidence, including original XML classes. Conflicting types remain
`CONFLICT`; an unclassified attachment keeps task classification `UNKNOWN`.
The runner can examine each source independently when establishing document
roles, rather than treat an auxiliary attachment as the accounting document.
`APDocumentBridge.from_task_sources(task)` accepts the existing replay loader's
`APTaskSources`. It preserves extraction unknowns on each source and retains
failed/unavailable attachments as `APSourceIssue`, without manufacturing facts.
An extraction `unknowns` entry called `MISSING` is still an operational unknown,
not an evidenced source absence. `financial_sources`, `notice_sources`, and
`unclassified_sources` expose existing source classifications independently;
selecting a complete accounting source set remains a runner decision.

`field(name)`, `facts.text(name)`, `facts.integer(name)` and `facts.date(name)`
return `APField` objects. Resolution uses `ap_rejections.resolve_field`, so all
equal candidates retain their evidence, while contradictions select no value.
The statuses are `RESOLVED`, `MISSING` (evidenced `None` or blank text),
`UNKNOWN` (no observed facts), `CONFLICT`, and `INVALID` (wrong typed value).
An extractor's failure to observe a field is never evidence that it is absent.
Header convenience fields include supplier/recipient identifiers, document
number/date, currency, net/tax/gross/payable cents, withholding and retention.
Dates remain ISO strings; `date_value` exposes `datetime.date` when resolved.
Payable and gross are distinct: neither becomes the other by arithmetic.

Each `APLineFacts` retains the attachment path and the one-based row index.
`quantity_milli` and `unit_price_e4` are integer normalized observations;
`quantity` is an exact Decimal view in original units and `unit_price_cents`
is an exact Decimal view in cents. These conversions do not round under the
caller's Decimal context. Signs are preserved for subsequent credit-note
handling. Missing units, prices or quantities stay unknown. No unit, zero
amount, VAT rate, applicability flag, or PO split is supplied by default.

Source `amount_cents` and `net_cents` remain separate. References keep their
literal names and scope, including ambiguous Facturae transaction references,
correction details, delivery rows and CFDI related UUIDs. A transaction
reference does not automatically become a purchase order or receipt ID.
Raw source extensions remain available through `source.raw` and normalized
extensions through `source.facts`; no literal source label is reinterpreted.
Full normalization diagnostics retain their messages and evidence in
`source.normalization_diagnostics`, alongside the compact diagnostic codes.

`task.header` resolves consensus across independent attachments. Invoice
`line.N.*` fields are excluded from this merge; `task.field("line.N...")`
returns `UNKNOWN` with `ATTACHMENT_SCOPE_REQUIRED`. `task.lines` lists observed
rows with source-qualified IDs for inspection, without asserting that rows
from two attachments are distinct billable rows. The runner must establish a
complete accounting row set and any cross-format correspondence before
allocation or posting. The bridge does not sum attachments, align row numbers,
choose a primary attachment, check line completeness or turn source diagnostics
into `REJECT`, `HOLD`, `DUPLICATE` or `NOT_INVOICE` decisions.

Synthetic integration tests cover identity catalog handoff, PDF/XML header
conflicts, evidenced absence, exact quantities/prices, missing units, raw
extensions, source-separated rows, classification and source integrity.
