# Phase notice context (#140)

`resolve_phase_notice_context(prepared: APPreparedSources, *, data: PhaseData,
scope: ApScope)` returns an immutable `PhaseNoticeContext` for one invoice scope.
The prepared loader must authenticate the source manifest and originals first.
This adapter neither extracts nor contacts a provider, reads Golden, writes AP
rows, executes ERP actions or consumes receipts.

The snapshot exposes `timeline`, `unknown_event_kinds`, `incomplete_sources`,
`event_inventory_evidence`, `notice_results`, `evidence`, `diagnostics`, original
`bank_event_fields`, and inspected ERP/task `source_hashes`. Pass these directly
to the corresponding coordinator fields. In particular, the coordinator also
needs the invoice's **observed** `invoice_bank_iban`; the snapshot never chooses
an invoice bank account. `strict_invoice_events` remains responsible for the
invoice-date/reception query and operative bank verification.

## Scope evidence

Closed scope aliases accept canonical fields and their literal `raw.` forms:

| Role | Accepted observations |
|---|---|
| Vendor ID | `vendor`, `vendor_id`, verified against the active master |
| Ordinary notice's vendor tax ID | `supplier_tax_id`, `vendor_tax_id`, exact `IdentityCatalog` match |
| Certificate's subject tax ID | `certificate_tax_id`, `certificate_subject_tax_id`, `subject_tax_id`, `holder_tax_id` |
| Company | `company`, `company_code`, or exact `recipient_tax_id` |
| Currency | `currency`, `document_currency` |

Conflicting IDs, explicit unknown candidates or absent required scope preserve
UNKNOWN. A certificate's issuer `supplier_tax_id` is never its certified subject.
Sender domains and titles never establish vendor, company, currency or signature.
Ordinary operative notices require proven vendor, company and document currency;
the vendor's default currency never fills an absent inbox currency.

A contractor certificate is nonmonetary tax status under policy §2.2.4. Its
identified subject and explicit vendor-company affiliation permit projection to
the queried invoice's currency and company when the certificate has no contrary
scope observations. This is a documented policy inference, with policy/master
evidence retained in the event, rather than an observed document currency. An
explicit different company/currency remains outside the queried scope.

## Inventory and ERP

Negative inventory requires exact coverage of `tasks/ap_documents.json`, the
verified prepared-source fingerprint, explicit source classifications and the
corresponding active ERP catalogue. Traversal alone cannot establish absence.
Failed/unclassified sources or unknown scope invalidate all kinds. A scoped
notice with unresolved operative facts invalidates only its known kind.
Observably foreign sources can be excluded, retaining exact identity evidence.

The explicit contractor-certificate catalogue can establish registered absence.
Rows with missing subject/reference/validity prerequisites remove that claim.
The AP vendor's explicit `alternative_payee` and `garnishments` fields establish
their registered inventories; omitted keys do not manufacture `None` or `[]`.
AR `factoring_assignments` is a customer-credit catalogue and cannot establish
absence of assignments to AP suppliers. `bank_history` contains accounts, not
signature/certificate/registration facts, so it cannot prove that no registered
signed bank letter exists. A positively verified inbox letter can still provide
support without that negative claim, unless another source makes it uncertain.

ERP conversion reuses `registered_events`, retaining original clocks and adding
source hashes. Explicit factor invoice restrictions/expiry and garnishment
restrictions/expiry are preserved. A missing certificate catalogue remains
unknown while other known vendor events survive. Registered embargoes without
reception keep that absence; the strict query prevents issue/effective dates
from becoming an invented reception. ERP certificate issue dates remain validity
dates, with no invented received timestamp.

Fresh `PhaseData` avoids a stale caller cache. Vendors, companies, available
certificates and task/phase files are hashed before reading and verified again
before returning. Each path is checked with the source runner's `_safe_file`
before a byte read, including the phase clock before constructing fresh
`PhaseData` and paths rechecked at final verification. Symlinks to Golden or
outside the active phase are rejected before their target bytes are opened.
Results are independent of prepared-task/attachment order;
input facts remain unchanged and returned bank-field mappings are read-only.

## Targeted verification

`.venv/bin/python -m unittest tests.test_ap_phase_notice_context -v` exercises
eleven synthetic November 2031 scenarios: signed bank support and distinct clocks,
missing proofs, unread sources, foreign scopes, scope contradictions, certificate
subject/currency projection, registered restrictions/unknown reception,
informational documents without events, immutable deterministic replay,
incomplete inventories, source changes and forbidden source symlinks.
This does not validate a complete July or September accounting run.
