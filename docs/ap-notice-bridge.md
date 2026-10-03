# Strict AP notice integration (#140)

`ap_notice_bridge` supplies explicit observations to the existing `apply_notice`
and `invoice_state` engines. It does not change their policies, write ERP, read
Golden, or call a provider. Its inputs are normalized attachment `Fact` candidates,
the original message's evidence-bearing `DocumentFacts`, and an explicitly
resolved company/vendor/document-currency scope.

`resolve_ap_notice(document_type, *, fields, company, vendor, currency, metadata,
state=ApTimelineState())` returns the existing `NoticeResolution`. UNKNOWN keeps
the supplied state and all source evidence. PROFORMA and VENDOR_STATEMENT return
NOT_INVOICE/NONE without an event. Required/conflicting/invalid notice facts cannot
register an event. Exact replay is idempotent; a changed interpretation under the
same task/attachment identity returns UNKNOWN with a conflict diagnostic.

Metadata `doc_id` and `received_at` must each have agreed candidates. Reception is
read only from metadata `received_at`; document dates cannot replace it. Issue and
validity dates remain independent from reception. A contractor certificate's
explicit `certificate_issue_date`, `certificate_issued_on` or `issued_on` can supply
its start; an unlabeled generic `document_date` cannot. Reversed or ambiguous
validity dates produce UNKNOWN.

The following aliases are closed lists. Each name also has an explicit `raw.`
counterpart (for example `raw.signed`); no title, fuzzy label, issuer name, domain,
or arbitrary prose supplies an operative fact. Alias candidates must all agree,
including explicit `None` candidates. Original Evidence is retained even when
aliases normalize to the same value or contradict one another.

| Observation | Accepted names |
|---|---|
| Certificate start | `certificate_valid_from`, `valid_from`, `certificate_issue_date`, `certificate_issued_on`, `issued_on` |
| Certificate expiry | `certificate_valid_until`, `certificate_expiry_date`, `contractor_certificate_valid_until`, `certificate_tax_valid_until`, `valid_until` |
| Assignment start | `factoring_effective_date`, `valid_from` |
| Assignment expiry | `factoring_valid_until`, `factoring_expiry_date`, `valid_until` |
| Garnishment start / end | `embargo_date`, `valid_from` / `embargo_valid_until`, `valid_until` |
| Bank change start / end | `bank_details_effective_date`, `valid_from` / `bank_details_valid_until`, `valid_until` |
| Referenced invoice | `assigned_invoice_number`, `referenced_invoice_number`, `invoice_reference`, `invoice_number`, `original_invoice_reference` |
| Factor account | `factor_iban`, `new_iban`, `iban`, `value` |
| New bank account | `new_iban`, `iban`, `value` |
| Letter signature | `signed`, `signature_present`, `bank_letter_signed` |
| Bank certificate | `bank_certificate_present`, `bank_certificate_attached` |
| Explicit existing bank registration | `bank_change_registered`, `registered_bank_change` |
| Direct scope IDs, when observed | `company`, `company_code`; `vendor`, `vendor_id`; `currency`, `document_currency` |

`document_number` identifies the notice itself and cannot become its assigned
invoice reference. A source assignment's explicit invoice restriction and expiry
survive into `ApEvent.invoice_number` and `valid_until`. Dates use the existing
source date parser; account identifiers remove presentation separators while
retaining literal Evidence. Booleans require actual boolean Fact values, never
string truthiness. Bank verification requires BOTH signature and bank certificate
observations to be True. `verified=True`, a matching sender domain and a title
stating “signed letter” do not replace either observation.

`strict_invoice_events(events, scope, invoice_date, received_at, month, *,
invoice_number=None, bank_iban=None, complete_kinds=(), inventory_evidence=None,
uncertain_kinds=(), incomplete_sources=(), bank_fields=None)` returns
`StrictInvoiceEventSnapshot`. `snapshot.state` is the real `InvoiceEventState` for
the HOLD/payment engines; `snapshot.events` contains the validated copies,
`snapshot.complete_kinds` and `snapshot.inventory_evidence` contain only effective
completeness claims. Inventory evidence is an immutable mapping.

For each queried bank event, pass its original observations in
`bank_fields[(event.scope, event.event_id)]`. This rechecks both bank proofs even
when a legacy adapter supplied `verified=True`. Without those observations, the
event's verification stays UNKNOWN. The account observed in those same facts must
agree with `event.value`; conflicting, missing or explicitly absent account
candidates cannot authorize it. All original bank-field Evidence is retained in
the event copy, including proof of conflicting accounts or scope IDs. Direct
company/vendor/currency observations, when present, must agree with the resolved
event scope. An explicitly unverified input event cannot be promoted.

Source start/expiry candidates, when present, must agree with the event's dates;
copies retain those dates. A queried invoice outside an explicit bank-authorization
expiry cannot use that expired evidence as support and stays UNKNOWN. An event
without reception additionally requires an explicit True bank-registration Fact
through the closed aliases above; a missing timestamp cannot silently turn an
inbox letter into an ERP registration. A registered event keeps `received_at=None`
without inventing a clock. The original input event is never changed.

For a garnishment whose reception is unknown, a copy with `valid_from=None`
prevents the chronology engine's ERP snapshot fallback from asserting that it
preceded every invoice. The original date Evidence remains available; no receipt
timestamp is invented. A documented reception uses the existing engine's strict
before/after ordering. The caller must obtain notices through `resolve_ap_notice`
to preserve invoice restrictions and expiry; this function cannot recover data
discarded by another adapter.

A completeness claim requires source Evidence for that kind. The caller must
pass an UNKNOWN notice's kind in `uncertain_kinds`, and every failed or unclassified
source in `incomplete_sources`. Source failures invalidate all completeness claims;
uncertain kinds invalidate their own. A known factor may still prove assignment
existence, but an unresolved competing notice cannot settle its recipient or
bank. A known bank letter cannot settle an incomplete inventory of competing bank
instructions. Absence stays UNKNOWN without a complete, evidenced inventory.

Validation: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p
'test_ap_notice_bridge.py' -v`. Synthetic November 2031 cases exercise the real
engines, including unsigned bank instructions, assignment invoice/expiry limits,
unknown reception, contradictory candidates, payment blocking, scope isolation,
unchanged inputs and replay with network unavailable. These checks do not claim
complete July or September AP acceptance.
