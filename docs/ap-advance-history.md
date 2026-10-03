# Recorded advance baseline — #54

`resolve_historical_advances(company=..., vendor=..., as_of=...,
journal_entries=..., purchase_orders=..., vendors=..., ap_invoices=..., tax_catalog=...,
inventory_complete=True)` reconstructs one vendor's advance balances through an
explicit posting-date cutoff. Inputs are copied; the solver does not repost or
repair historical journals. A complete source inventory is required, including
manual 407 movements. An unresolved movement potentially belonging to the vendor
returns `UNKNOWN` with no usable balances, preventing an invented free capacity.

The complete AP register is checked alongside the complete journal. An observed
invoice application with a missing posting link or no corroborating 407 movement
cannot leave a deposit available. Unknown document types do not prove absence.
Linked posting clocks must agree before excluding a future movement; direct
document-currency applications must match the header's advance residual.

An original 407 debit requires a literal PO/position assignment, matching
company/vendor/document currency, an existing position, a PO predating the
deposit, and an affiliated vendor master. Any observed supplier/407 partner must
agree with that PO. A null 407 partner in a source journal is corroborated through
the PO and supplier; the original remains unchanged and its validation error is
preserved in `reference_entry_errors`. No other source validation error is
waived. The resulting `AdvanceBalance` contains the derived vendor, exact source
journal id, original invoice/date/PO and document/booked local cents.

Applications name the original deposit invoice literally within company/vendor
scope. Ambiguous or absent references abstain. Explicit same-currency document
cents are preserved. Some original foreign applications are recorded in local
currency: their local amounts cannot supply foreign cents. A unique linked AP
invoice must corroborate vendor/currency/number/date, the supplier's document
payable and the unsigned gross/deduction headers. With one 407 application, its
foreign consumption is the observed gross less withholding, guarantee and
payable. Base, deductible VAT, withholding and guarantee must also match the
journal's observed document amounts, using the active tax catalogue. Mixed
non-deductible/reverse/import treatment lacking an explicit decomposition remains
unknown. Missing links, multiple 407 lines or unexplained amounts abstain.

Cumulative document and local consumption must not exceed the deposit and must
agree with exact rational historical carrying-value rounding. Applications are
grouped by observed posting day, verifying each day's cumulative balance without
inventing precedence between same-day entries from IDs or input-list order. Exhaustion
preserves the remaining booked cents. The result includes all documentary ERP
locators; pass resolved balances into `AdvanceState` together with existing
posted-event and credit baselines. The caller still establishes new-document PO
approval, advance classification and actual application-to-invoice-line binding;
neither PO existence nor historical balance authorizes those decisions.

The source regression reconstructs July's three foreign advances and their full
consumption from the original ERP, retaining the three null-partner reference
diagnostics. Twelve focused regressions cover cutoff, immutable sources, exact
scope/reference, foreign/local distinctions, missing/ambiguous history,
inconsistent carrying amounts, source/header contradictions, input permutations,
same-day grouping, broken application links, contradictory posting clocks and
unattributed manual movements. No golden,
provider or source modification is used. This resolves the baseline adapter;
credit receipt/advance restoration and full-phase evaluation remain separate.

```sh
KALMORA_PHASE_ERP=/path/participant/phase_dev/erp .venv/bin/python -m unittest discover -s tests -p test_ap_advance_history.py -v
```
