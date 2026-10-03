# M4-06 duplicate receipts and factoring

## Decision rules

Historical duplicate evidence is accepted only for an earlier journal entry that posts the same positive bank cash and one matching AR credit for the same customer, company, and currency. The invoice must have no positive 430 balance as of the new receipt, and no exact open invoice can receive the amount. In-run duplicate evidence uses the same company/currency/customer/amount key. This prevents an equal amount in another entity or currency from being attributed to the wrong invoice.

An assignment to a factor clears the customer's 430 item. If the customer later pays Kalmora for that ceded invoice, the amount is credited to the factor account 553, not applied to the already-cleared customer invoice. The amount and as-of assignment must match uniquely.

## Phase evidence

The July run identifies two misdirected payments to Banco Atlántico Factoring:

- `BL0000085` matches `OB26-00022` for 89,504,793 cents (€895,047.93). The ERP records a 13 April factoring assignment and a same-day credit of the full invoice from 430 to 553.
- `BL0000088` matches `OB26-00032` for 101,285,462 cents (€1,012,854.62). The ERP records a 13 May factoring assignment and a same-day credit of the full invoice from 430 to 553.

Both rows emit `FACTORED_MISDIRECTED` and credit 553; they do not credit 430 a second time. `BL0000706` is supported separately by its normalized remittance snapshot, which identifies `OB26-00025` and agrees exactly with the 7 July receipt. `BL0000707` remains unresolved: it has no matching normalized remittance evidence, and its amount alone does not identify an invoice or a duplicate.

Regression tests cover a second in-run receipt after clearing an invoice, a duplicate supported by a fully posted historical cash/AR pair, company scoping for equal payments, and factor settlement without a second AR credit. No PDF or XML source is used as a solver input; the remittance snapshot is read through `DocumentRouter(use_preparsed=True)` with source path and hash validation.

## Validation

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_ar_cash*.py' -v
PYTHONPATH=src python -m kalmora solve-ar-cash participant/phase_dev \
  --use-preparsed --normalized-dir participant/normalized_sources \
  --output /tmp/ar_cash-m4-06.jsonl
PYTHONPATH=src python -m kalmora evaluate participant/phase_dev \
  /tmp/submission-m4-06 --structure-only
python participant/score.py participant/phase_dev participant/phase_dev \
  /tmp/submission-m4-06
```

The AR Cash and remittance suites pass (27 tests). The normalized-source run emits 32 rows: 27 decided and 5 unresolved. Structure validation reports no diagnostics and zero separation violations. The official evaluator reports `ar_cash = 0.8922` (27/32 fully correct), unchanged from the previous M4 result.

## Issue status

Issue #83 depends on #80 and #81; both are still open. This change hardens duplicate and factoring decisions and documents the phase evidence, but the full M4 acceptance remains gated by those dependencies. Keep #83 open until they are resolved and the end-to-end result is revalidated.
