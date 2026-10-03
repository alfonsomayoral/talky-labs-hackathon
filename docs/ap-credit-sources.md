# Exact original-invoice resolution — #54

`CreditOriginalCatalog(invoices=..., journal_entries=...,
inventory_complete=True)` snapshots the complete active-phase AP invoice and
recorded-journal inventories. `resolve(company=..., vendor=..., currency=...,
invoice_date=..., original_number=Fact(...), original_series=...)` matches the
literal original number within that exact company/vendor/document-currency
scope. Supply the evidenced original reference (for example Facturae
`corrective.document_number`), not this credit note's own number or a generic
related-document UUID. No number normalization, prefix removal, series
concatenation, amount matching or vendor-name heuristic is applied.

A unique invoice must have an explicit link to a valid recorded AP/KR journal.
Its number, issue date, currency and supplier are corroborated against that
journal. An observed nonempty series requires its own exact ERP field; an unknown
series representation remains unresolved. The original must predate or share
the credit document's issue date. The actual supplier account (400/410) and cost
objects are preserved rather than replaced with current vendor defaults. Local
header currency may differ from evidenced foreign line currency, but foreign
lines require explicit document cents. A registered HOLD with a real posting is
still a recorded original; an unposted invoice never supplies an invented entry.

`RESOLVED` exposes a copied original journal, its reconciliation account,
canonical snapshot SHA-256 and all documentary/ERP locators. Other statuses
(`UNKNOWN`, `NOT_FOUND`, `AMBIGUOUS`, `CONFLICT`) expose no postable journal or
account. Missing or incomplete inventories cannot prove uniqueness. Duplicate
source identities raise before resolution. Neither source records nor the
catalogue snapshot can be changed through the returned copy.

The caller must still evidence the credited line-to-original-line mapping before
constructing `CreditReference`. Original binding is not fiscal authorization:
the journal engine checks the original treatment and cumulative consumption in
`AdvanceState.credits`. Previous credit consumption, advance/receipt restoration
and final task decisions remain explicit integration responsibilities. This
catalogue does not post originals again or infer that their remaining balance is
unused. CFDI related UUIDs need their own evidenced ERP identity mapping and
relationship interpretation; they do not automatically identify a numbered
original invoice through this API.

Six regressions cover exact identity, ambiguity/completeness, series, broken
posting links, dates, foreign cents, immutable sources and integration with the
real atomic AP transaction. A failed AP header consumes no credit balance; two
valid partial credits exhaust the original and a third fails. With July ERP
enabled, direct XML extraction plus exact master identity resolution reproduces
the three observed Facturae corrective references: two bind to recorded
originals and one remains `NOT_FOUND`. This is original binding evidence, not a
claim that those three tasks have complete accounting decisions. No golden or
provider is used.

```sh
KALMORA_PHASE_ERP=/path/participant/phase_dev/erp .venv/bin/python -m unittest discover -s tests -p test_ap_credit_sources.py -v
```
