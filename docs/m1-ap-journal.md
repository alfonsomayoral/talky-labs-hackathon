# AP journal assembly, credit notes and advances (#54)

`kalmora.ap_journal` combines #51 net valuation, #52 tax and #53 withholding
components into M0 `JournalEntry`/`JournalLine` dictionaries. It preserves
document cents and currencies, invoice/PO assignments, supplier reconciliation
accounts, partners and cost objects. Every result passes `validate_entry` with
the caller's optional master/date context. It performs no I/O or ledger writes.
An explicit `POST` or `POST_PAYMENT_BLOCK` decision is required. Other decisions
raise before producing tax/supplier journals or changing tentative state.

All three calculation factories now attach `APComponentScope` (in its own model
module, imported directly). The assembler requires an exact company, vendor,
currency, document id, invoice date and eligibility decision match. Tax and
withholding standalone APIs remain compatible, but callers must additionally
pass `vendor`/`invoice_id` to tax and `invoice_id` to withholding before journal
assembly. Legacy/partial scopes and components for another document or FX date
cannot authorize a journal. This is factory input provenance, not a scope label
invented later by the assembler.

## Invoices and credit notes

`build_ap_journal` accepts explicit invoice scope, dates, reconciliation account,
`ValuationResult`, `TaxResult`, and `WithholdingResult`. The fiscal and valued
bases must agree per invoice line, including zero-base DUA components. Valuation
factories retain cost assignments even when PO variance is zero; non-deductible
VAT must use that exact expense/asset assignment. The supplier's document payable is gross less tax withholding, guarantee
and applied document advances; its local payable is the exact balanced residual
after per-line FX rounding. Currency rounding is not booked as an invented FX
gain/loss. Mixed fiscal bases remain separate: notary fees can carry IRPF while
exempt disbursements do not (original example `1000-2025-5100000016`).

For `CREDIT_NOTE`, supply `CreditReference(line_id, original_entry, original_line)`
for the original account/partner/cost imputation. The source journal must be
valid, identify an entry, match company/vendor/currency/reconciliation account,
and support the credited amount, aggregated across all references to each
original line. Conflicting snapshots of one original journal and ambiguous
imputation mappings fail. New base components must preserve those dimensions
and the original fiscal treatment. An unlabelled GR/IR base requires unambiguous
original VAT evidence; missing evidence never authorizes a new treatment.
Original tax quotas cap their reversals, including explicit zero-base DUA
references. Retention/guarantee reversals require original deductions and proven
eligible bases, using the calculation factory's validated catalogue snapshot.
Missing or invented original deductions fail, including partial credits whose
deduction basis cannot be resolved. The builder reverses
debit/credit sides of base, deductible/reverse VAT, withholdings, guarantee and
supplier lines. Document amounts remain unsigned as in the AP contract.

Original-reference extraction/resolution belongs upstream. The builder does not
guess an original invoice from a similar amount/vendor or change to current
vendor defaults. Credit-note advance restoration is not automatic: such a
refund/reinstatement needs separate resolved evidence, not ordinary application
instructions. Cumulative original-invoice credit tracking is not this advance
state's responsibility; upstream duplicate/original-reference controls remain
required for complete document processing.

## Foreign down-payment requests

`build_down_payment_request` requires a foreign vendor country evidenced by the
matching `vendor_master` id, country and company affiliation, and an
`ApprovedAdvanceOrder(company, vendor, currency, po, approved, approval_reference)`.
Unknown/false approval blocks; existence or `created_on` in the PO master is not
invented approval evidence. The policy entry is Dr 40700000 / Cr 40000000,
including the vendor on both open-item accounts. It returns the new historical
advance balance in tentative state. This deliberately keeps M0's partner
invariant despite original advance entries that have `partner=null` on 407.

`ap_advance_sources.resolve_advance_sources` supplies this resolved order/master
from an exact documentary PO `Fact`, an `AdvanceApproval` containing an observed
PO and literal boolean approval, and phase PO/vendor/company masters. The
approval pair must describe one evidenced source statement; PO existence alone
never establishes approval. Company/currency, creation date, affiliation and
foreign country are checked. Observed supplier/recipient tax IDs are corroborated
through `IdentityCatalog`; contradictory, unknown-to-master or ambiguous observed
IDs cannot be discarded to favor the PO. If a request has no tax ID, the exact
documentary approved PO and affiliated master independently establish its
counterparty. Missing PO/approval/affiliation/country exposes no usable order or
master. Every source and failed condition remains in the resolution audit.
Feed a `RESOLVED` result into `build_down_payment_request` with its master country,
explicit eligible decision and monetary/FX inputs. No source journal is repaired,
no amount/doc ID special case determines the supplier and no state is committed.
The helper snapshots its inputs and the journal preserves that derived vendor
on both 407 and reconciliation lines.

## Historical advance application

`AdvanceBalance` carries original document cents and booked local cents, the
source invoice/date/PO, and cumulative document/local consumption.
`AdvanceApplication` supplies amount, classification and evidence; unknown
classification blocks. The invoice must explicitly resolve the same PO and
company/vendor/currency. Every application names an invoice line and an explicit
`InvoiceLineOrder(line_id, po, base_doc, reference)` binding. Aggregate
applications cannot exceed that line's invoiced PO portion, and PO portions
cannot exceed the valued line. These limits apply to both classifications.
Multiple advances are allowed, without duplicate application mappings or
over-consumption. Applications originating after the invoice fail.

Historical local consumption is calculated from the **original** booked carrying
amount using cumulative exact rational rounding. The final application consumes
the remaining booked cents, so splitting an advance cannot introduce residual
drift. No rounded rate is calculated from the residual balance. Local-currency
advances must have equal original document/local amounts. Any positive document
posting that rounds to zero locally is rejected before journal assembly because
its debit/credit direction cannot be represented; incoming state stays intact.
Applied 407 lines
keep original document amount/currency and source-invoice assignment.

For an evidenced `NON_MONETARY` advance, explicitly supply its original
expense/asset `CostAssignment`, which must match the linked valued invoice line.
The difference between historical carrying and
invoice-date value adjusts that imputation. The cost includes the prepaid portion
at its historical value and the outstanding portion at invoice-date FX. There is
no invented monetary FX gain/loss. For an evidenced `MONETARY` claim, the same
difference uses 66800000 (loss) or 76800000 (gain) instead; no cost assignment is
accepted. The package's historical import cases support the non-monetary case,
not a default classification for every advance.

The manual says to apply advances at historical FX but does not fully specify
asset measurement. Original ERP entries establish that convention:

| PO | Advance local cents | Full current-rate asset | Asset recorded | Supplier recorded |
|---|---:|---:|---:|---:|
| 4500014449 | 6042755 | 20481113 | 20379534 | 14336779 |
| 4500016825 | 3972799 | 13459440 | 13394407 | 9421608 |
| 4500020749 | 2356021 | 7742560 | 7775813 | 5419792 |

The first invoice has USD cents 21200000, prepaid 6360000. At invoice-date rate
1.0351, the prepaid part would be 6144334 EUR cents; the recorded asset is
20481113 − 6144334 + 6042755 = 20379534. Its supplier is the 14840000 outstanding
USD cents at current rate: 14336779. Source entry pairs are
`1100-2025-5100000215/0339`, `1100-2025-5100000851/0970`, and
`1100-2026-5100000207/0357`; the source-only test reproduces all account, partner,
cost-object and amount totals exactly, without golden.

## State and integration boundary

`APJournalResult.state` is an immutable tentative `AdvanceState`. Only commit it
after successful projected-ledger insertion. Replaying the same
`(company, vendor, currency, doc_id)` fails; a failed calculation or master
validation leaves the incoming state unchanged. Reconstruction from saved state
retains consumed balances and events. M0 `Ledger.add_entry` supplies the final
event/stage duplicate protection when persisting journals.

This module does not serialize `ap.jsonl`, read extraction facts or run decision
precedence. #55 owns that orchestration, while #32/#35 keep contracts/scoring.
PO approval, credit originals, historical advance balances/classification and
cost assignments must be resolved inputs until their adapters exist. No complete
305-document M1 result or golden accuracy is claimed by these component tests.

```sh
PYTHONPATH=src python3.12 -m unittest discover -s tests -p test_ap_journal.py -v
KALMORA_PHASE_ERP=/path/participant/phase_dev/erp PYTHONPATH=src python3.12 -m unittest discover -s tests -p test_ap_journal.py -v
```
