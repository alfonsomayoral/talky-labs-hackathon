# M6 issue-by-issue status

Implementation tracking #20–#23 and #95–#104 is **CLOSED** at the user's request.
The unresolved accounting work is consolidated in **#251 (OPEN)**; final real-flow
execution outside golden, including September, is **#171 (OPEN)**. Existing PR
#197 and #277 are merged. The corrected real deterministic workflow has now
executed in July and September; see [REAL_FLOW_REVIEW.md](REAL_FLOW_REVIEW.md).
Closure of the modular tracking is not real-flow acceptance.
The table below preserves the original delivery evidence and its remaining work;
current score evidence is in `SCORE_INVESTIGATION.md`.

| Issue | Delivered modular implementation/evidence | Remaining evidence or acceptance |
|---|---|---|
| #95 M6-01 | Saved original service periods, historical carry-over, receipt coverage including HOLD, PO/GR-IR/IC exclusion controls; 76 documentary observations | Full discrete-service coverage and original-document acceptance review; real #137/M1/M5 handoffs |
| #96 M6-02 | Historical median daily-rate and separately documented discrete monthly exposure estimators; cost-object samples and min/max sensitivity | Material estimation discrepancies remain; no target-calibrated retuning |
| #97 M6-03 | 54 detailed accrual rows/45 keys, CC/PEP and supplier retained; aggregate and strict line comparison | Reference is 57 rows/45 keys; two missing/two extra identities and amount/cost-object differences need resolution |
| #98 M6-04 | Positive/negative prepaid movements, existing 480, monthly allocation and last residual; nine July identities; boundary tests | Five 1–2-cent reference rounding differences require review; real AP receipt/posting coverage |
| #99 M6-05 | Shared CertificationFacts/Chapter, original current certification delta, customer and chapter PEP; exact July amount | Real M2 pending-certificate delivery, not fixture SKIP status |
| #100 M6-06 | FX after dependency projection; USD/GBP, EUR-to-MXN loan/interests and USD bank; eight reference amounts exact | Six extra open historical USD credit notes and strict document-currency representation need reconciliation; real producer positions |
| #101 M6-07 | After-cash ageing and required-minus-existing 490; threshold, insolvency, guarantees, exclusions and reversal tests; exact July amount | Real M3/M4 applications and ageing completeness; external review |
| #102 M6-08 | Minimal shared CloseType extension; invoice-by-invoice 430-to-436 in declaration month only; multiple invoices/rerun/prior-month tests | July has no such event; real-flow variation evidence and review |
| #103 M6-09 | Month-end-only entry validation; historical reversals read; no new day-one reversals; ERP immutability and idempotence tests | Real pipeline rerun/event-stage ownership evidence |
| #104 M6-10 | Frozen-output evaluator, original/pre/final books, strict and aggregate differences, per-account impact, replay and real CI logs | Original close component 78.507%, not full accounting acceptance; review and real integration |
| #171 M6-11 | Real deterministic AP/bank/AR/IC-to-M6 execution in July and September; positive IC coverage, frozen hashes and exact replay | Review the four AP company differences and documented source/reference discrepancies before accepting the full accounting flow |

Epics #20 (accruals), #21 (prepaids/WIP), #22 (FX/customers), #23 (export/validation)
are closed; milestone 7 remains open with #171 and #251. Issues #20, #22,
#95–#97 and #100 were closed as superseded, with their unresolved scope transferred
to those issues; the other modular tracking issues were closed as completed.
CI proves tested code behavior; it does not replace the missing accounting or
real-flow acceptance evidence.
