# M6 development method (fixed before close-target evaluation)

This is **simulated integration**, not acceptance of #171. The solver runs from
sealed contracts and shared Ledger, RateTable, JournalEntry, JournalLine,
Evidence, DocumentFacts and CloseRow interfaces. It does not import a producer,
a document extractor or an evaluator. Its own entry point avoids global CLI/M5
conflicts. Only the shared CloseType is extended with DOUBTFUL_RECLASS.

## Inputs and boundaries

`tools/m6_fixture.py` is an explicitly authorized development adapter. It reads
only AP, billing, bank reconciliation, receipts and IC fixture outputs. Its CLI
installs an audit guard denying close and balance targets. Sources used for
coverage, unpaid document principal, due dates, insolvency and certifications
are original ERP, inbox and bank data; all are hashed. Shared DocumentRouter
supplies parsed documents and shared DocumentFacts retains observed periods.
No LLM is built or called. The #137 extractor's DocumentFacts is the real-provider
interface; deterministic original observations are labelled fixture versions,
not misrepresented as LLM extraction acceptance.

The contract requires all five handoffs, phase/month, hashes, completeness,
expected/observed coverage and event/stage owners. AP results retain every
receipt status, including HOLD, REJECT, DUPLICATE and NOT_INVOICE; only authorized
postings enter the projection. IC fixture coverage assumes its exception report
is exhaustive; that is not real pair-reconciliation evidence. Missing coverage
fails closed; replacing fixtures with real handoffs does not replace the solver.

ERP is the only opening accounting source. AP/AR master balances identify facts,
not additional journal entries. Three independent books are retained: original
ERP, after dependencies and after M6. Original IDs, normalized AP business keys,
references and financial signatures prevent duplicate postings when IDs change.
Contradictory representations fail rather than being added twice.

## Rules and assumptions

- ACCRUAL: comparable supplier/service/cost-object history over twelve months, last
  three distinct observed periods, mean daily rate times uncovered days. Coverage
  is a union of evidenced invoice receptions, independently of posting decisions.
  HOLD, REJECT and DUPLICATE retain their observed periods and allocations; they
  do not create journal entries. An ambiguous cost allocation blocks the affected
  series rather than proving nonreceipt.
  Previous unbilled periods persist only when their linked invoice has not arrived.
  Posted invoice costs are additive within the same observed period and replace
  same-period close estimates. Reissued historical estimates retain the latest
  closing per obligation reference and interval before distinct obligations sum.
  For professionals, recurring monthly historical
  unbilled exposure requires repeated full-month observed coverage; isolated jobs
  do not prove a new month's consumption. A one-day service is never multiplied
  by every month day.
  The repeated-month evidence threshold is a conservative engineering assumption.
  Market representative fees are not accrued.
  Additional discrete consumption without evidence remains unknown. History is
  not posted again, unreversed accrual is deducted, and PO/GR-IR/IC ownership excludes
  the service. Min/max sampled rates are sensitivity bounds, not confidence limits.
- PREPAID: monthly straight-line coverage, half-up installment and final residual;
  required 480 minus the existing balance. Premium costs include non-deductible
  surcharges, not recoverable tax. Posted payment-blocked invoices are included.
  Historical installment number/term gives coverage when original inbox files are
  unavailable; the source journal is cited. Positive and negative adjustments work.
- WIP: reuse M2 CertificationFacts/Chapter and pending billing status. Current amount
  must equal cumulative minus previous and sum of chapters. No target amount input.
- FX: local carrying amount after every upstream adjustment versus original unpaid
  document principal at closing FX. Liability value growth is a credit; asset value
  growth a debit. Revaluation moves local cents only (foreign amount_doc=0). Original
  unassigned loan principal is tied to the unique documented agreement; this is
  explicit, not a hidden assignment rewrite. Supplier invoices and credit notes
  are revalued when their individual monetary positions remain open. No automatic
  vendor netting or credit-note exclusion is supported by policy §5; see the
  source review in `reviews/fx-evidence.md` for the reference discrepancy.
- BAD_DEBT: private/community balances after receipts; strictly >180 and >365 days,
  insolvency includes guarantees, public/group excluded. Required provision minus
  existing 490 supports both expense and release. Missing ageing blocks release.
  Half-cent provisions use the recorded historical truncation convention.
- DOUBTFUL_RECLASS: declaration month only; invoice assignment retained on both
  430 and 436 lines. One customer output can contain multiple invoice pairs.

Every entry is validated and dated month-end. No new day-one reversals are emitted;
existing reversals are in ERP. Re-running identical inputs is deterministic, and
replaying against the already-adjusted ledger creates no second adjustment.

## Validation sequence

1. Build the sealed upstream dependency fixture without any close/balance target.
2. Run the close engine and freeze all output hashes and its source-code hash.
3. Replay in a fresh process denying golden, original documents and network.
4. Only then load close/balance targets in the separate detailed evaluator.
5. Report unrounded balance discrepancies by company and account; never add EUR and
   MXN into one monetary total. Keep estimations, missing evidence and stage ownership
   separate from scorer tolerance. An aggregate pass is not a detail/assignment pass.
6. Modular tracking #20–#23 and #95–#104 is closed by user instruction. Keep M6,
   #251 (accounting/score work) and #171 (real execution outside golden and September)
   open pending their remaining evidence/review.
