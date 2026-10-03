# AP credits, advance applications and tentative restoration — #54

These deterministic APIs require explicit source facts. They perform no extraction,
LLM call, prefix recovery, original matching by money, source mutation or posting.
The original July package is read only. Golden is not an input.

## Original imputation and line bindings

`resolve_credit_line_bindings(original, lines)` consumes a resolved exact original
from `CreditOriginalCatalog`. An observed original line may be selected by a
`CreditLineBinding.original_line: Fact`; assignment/tax selectors also require
facts from the same associated documentary reference source. A selector from
another credit or an unlinked sibling document abstains. Without a line selector, a unique original accounting imputation can be
proved when its observed base lines all share account, partner, CC/WBS, PO
assignment, fiscal code and debit/credit direction. Equivalent multiple lines
produce `CreditReference(original_line=None, original_lines=(...))`, preserving
all actual indices. No invoice line, ordering or proportional allocation is
invented. Different imputations or unknown selectors return UNKNOWN.

The journal engine reserves `lines:[...]` for a group, and existing `line:n`
buckets remain unchanged. Overlapping grouped/granular usage is rejected:
previous group usage cannot be attributed to an arbitrary individual line later.
A source snapshot change, excess cumulative credit or different fiscal treatment
still aborts. Explicit 403 reconciliation accounts are supported as original AP
payables alongside 400/410.

## Positive historical consumption

`resolve_historical_credits(company, vendor, currency, as_of, inventory_complete,
inputs, ap_invoices, journal_entries, rates=None)` accepts evidenced
`HistoricalCreditInput` observations. A `credit_number` and `original_number`
from one document associate credit to original; the literal credit number must
agree with the AP register's exact GL link. Alternatively one associated source
may explicitly name both GL credit identity and original number. Equal amounts
never establish this relationship.

Typed valuation, tax, withholding and original references are supplied from
resolved observations. The actual historical AP/KG must have unique, concordant
scope/reference/clocks. The original must already be recorded by its posting
clock. The existing journal factories validate fiscal treatment and construct
bucket reservations. All signed local/document cents and accounting dimensions
must match the recorded KG, and header cents must match the components. Only
then are positive `CreditBalance.used_doc` and `covered_entries` exposed. Input
generators are copied once; source records and state remain unchanged.

`resolve_ap_opening_state(..., historical_credit_inputs=(), rates=None)` incorporates
this positive baseline while retaining its complete-inventory scanner. Every
uncovered relevant KG, broken link, unknown kind or potential manual refund
continues to return UNKNOWN. Historical covered postings do not create new
publications or events. Initialize once; do not reset between new documents.
Historical credit inputs involving restored advances are not reconstructed by
this resolver yet: they require a linked restoration/receipt baseline, not just
an ordinary journal reconstruction.

## New advance classification and application

`resolve_advance_applications(scope, state, applications, classifications, lines,
order_bindings)` binds `AdvanceApplicationFacts` to a unique existing advance in
company/vendor/currency/PO scope and to the explicit invoice line/PO portion.
Invoice, advance, amount, line and PO facts identify one source statement.
`AdvanceClassification` associates the same exact advance with MONETARY or
NON_MONETARY in one source document. Missing, conflicting or unassociated
classifications abstain. Country, PO existence, account or amount do not imply
a classification. Non-monetary applications preserve the line's cost assignment;
monetary applications have no cost reassignment. The journal engine computes
historical carrying cents and current-date cost/FX difference.

## Restoring advance and receipt consumption

`build_ap_journal(..., document_type="CREDIT_NOTE", credit_restorations=...)`
accepts `CreditAdvanceRestoration`: exact advance, original journal/407 line,
restored document cents, evidenced original application document cents,
classification reference and credited line. Associated `classification_advance`
and `classification_treatment` Facts are required and must agree with the exact
advance and requested treatment. Nonzero original deltas are also corroborated
against the recorded original cost/FX adjustment; an optional evidenced
`original_adjustment_line` disambiguates multiple original adjustment legs. A zero
delta never supplies a missing classification. The original 407 assignment must
name that deposit literally and the credited original imputation must match.
When several balances in the same scope share that deposit reference, associated
`application_original`, `application_advance` and `application_po` Facts must
identify the exact original journal, advance and PO from the same source document
as `application_doc`. Equal carrying amounts or deposit references do not select
one balance. Missing or contradictory associations abstain.
Locally booked foreign 407 never supplies inferred foreign cents: the explicit
application Fact is required. Cumulative `advance:n` credit buckets bound each
original application; restoring one invoice cannot consume another invoice's
application. A fully prepaid original retains supplier capacity zero and can
reverse its expense/407 without inventing an original reconciliation account or
a supplier line. Current advance usage decreases only in the returned tentative
state. Expense/cost or FX differences reverse according to the explicit treatment.

A carrying-rounding limit is deliberate: restoration must preserve both the
observed original application's local cents and `AdvanceBalance`'s cumulative
carry invariant. If removing an earlier application would require taking an
unobserved cent from another application, the operation abstains. It does not
invent a rounding adjustment or silently change historical attribution.

`prepare_ap_credit_restoration(journal_arguments, consumption,
receipt_restorations=(), restoration_state=ReceiptRestorationState())` builds the
real journal and returns `TentativeCreditRestoration(journal, consumption,
restoration_state, evidence)`. A `ReceiptRestoration` additionally requires:

- Exact credit line/original AP document/quantity Facts from one source statement.
- Recorded `Receipt` and original `QuantityAllocation`, with allocation evidence
  explicitly identifying that same original AP invoice.
- The actual original AP row and evidence proving its doc_id-to-journal link,
  scope, literal number/date and referenced original GR/IR PO position.
- Committed original receipt usage and remaining per-original restoration capacity.

Quantities are integer thousandths, never derived from money. Receipt usage is
released tentatively; original invoice/event identities are preserved. A sidecar
`ReceiptRestorationState` tracks restored quantities per original allocation so
another invoice's remaining consumption cannot fund repeated restoration.

The small finalizer `ap_credit_delivery.build_ap_credit_delivery` consumes these
results, calls the real `build_ap_row`, and exposes a frozen row plus advance,
receipt and restoration snapshots only after validation succeeds. A failed
journal, quantity proof, header or output check leaves every input unchanged;
discard tentative results and retry from the original snapshot. No file is
written. The #140 runner still needs to adopt all three snapshots atomically;
its `APTransactionState`/`APPostingInputs` are not modified here.

## Original evidence and remaining limits

The July original ERP has 56 AP/KG credit postings and 56 linked credit-note
register rows. None has a corresponding inbox directory; the register has no
original-reference field. These observed absences do not license prefix stripping
or matching by amount, so their positive history remains UNKNOWN without new
associated evidence. The source XML corrective references prove two exact
originals with unique imputations (one grouping three equivalent GL base lines),
and one reference remains NOT_FOUND in the initial historical ERP catalog. Group binding now resolves the two
imputations without claiming a document-to-specific-line mapping. A real-factory
regression initializes their original ERP baseline and validates two frozen AP
credit rows: 50.00 + 10.50 = 60.50 EUR and 1188.02 + 0 = 1188.02 EUR, preserving
original account/CC and fiscal codes. The third reference has an ordinary-invoice
original in the same July task phase; the existing v0 route uses that published
original. Historical-catalog absence is not a global source absence. These two
owned rows are partial evidence, not a complete monthly delivery.

407 journals expose recorded amounts, references and assignments, not a monetary
classification. These balances/applications are reconstructed independently by
`resolve_historical_advances`; new classification Facts must come from upstream
source evidence. Receipt restoration additionally needs historical per-invoice
allocation records: aggregate GR/IR money or aggregate consumption is insufficient.
No July state is reused in another phase. No evaluation IDs determine rules.

[Independent issue #54 acceptance](ap-credit-acceptance.md) maps the actual
criteria to implementation, source facts and validation. Historical KG coverage
and adoption by #140 are operation/integration boundaries, not extra module
acceptance criteria.

### Separate evaluation of the two owned original-source rows

The original-source regression above was additionally instrumented to capture
the unchanged `build_ap_credit_delivery` return bytes, with Golden inaccessible
to the producer. The 64 original sources it used had identical hashes before
and after production. A separate evaluator process loaded the original July
scorer and reference through `kalmora.evaluation`, selecting reference rows only
by the two document keys observed in the produced rows. Both rows match exactly,
including header, account/partner/CC/WBS aggregates, currency, document cents
and assignment; there are zero scored or unscored differences and no
`ENTRY_RULE`/`REFERENCE_ENTRY_RULE` diagnostics for this subset.

This evidence is `PARTIAL_OWNED_2_CREDITS`, with `monthly_score=null`, not a
305-task delivery or historical-restoration acceptance. The captured JSONL SHA-256
is `72f3d6d89f2200c5a5a120527a1fb74e49a036cac259d8e70b96dbdb2190bda7`;
the original scorer SHA-256 is
`b8adec99c609098c7781b4d34cd08ddd6c7d62830800ac9b37d5b1213ca0828e`.
The local reproducible capture/evaluation scripts, complete diagnostics and
source hashes are in `outputs/m1-owned-validation/owned-credit-evaluation/`.
No package signature manifest was available, so manifest verification is not
claimed. The independent reviewer performed this evaluation after reviewing
the implementation; the missing links and #140 adoption requirements remain.

Focused validation:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests \
KALMORA_PHASE_ERP=/path/participant/phase_dev/erp \
.venv/bin/python -m unittest test_ap_credit_bindings test_ap_credit_history \
  test_ap_advance_bindings test_ap_restoration test_ap_credit_sources \
  test_ap_advance_sources test_ap_journal test_ap_advance_history \
  test_ap_opening_state test_ap_credit_delivery -q
```
