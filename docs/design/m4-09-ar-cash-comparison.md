# M4-09 AR Cash comparison

## Compared fields

The evaluator compares each receipt by `bank_line` and reports:

- Customer identity.
- The multiset of application identifiers (`invoice` or `pagare`) and integer-cent amounts.
- Residual type and amount, plus the balanced adjustment lines (company, account, amount, partner and cost object).
- `residuals.invoice` as an explicit `unscored` difference. The official metric omits this reference, but the comparison report still exposes it so a wrong invoice cannot be hidden by a perfect score.

The comparator wraps the organizer's `score_ar_cash` for entity scores and reconciles the mean with the official module score. It does not use `golden` from solver code.

## Phase comparison

The normalized-source July submission contains 32 receipts: 27 exact and 5 partial according to the evaluator, with official score **0.8921875** (displayed as 0.8922). The comparator reconciles the mean to the same official score. It reports five application differences, one residual type/amount difference, five adjustment-line differences, and one `residuals.invoice` difference under `unscored`.

For `BL0000706`, the integrated #85 regression separately checks that bank import and AR application are distinct, 555 clears to zero, and the bank balance is unchanged by AR application.

## Regression coverage

New evaluator tests verify both sides of the contract:

1. A change only to the invoice attached to a residual leaves the score at 1.0 but appears in `entity.unscored` as `residuals.invoice`.
2. A changed invoice/pagare identifier or amount, customer, or adjustment entry appears in the scored entity differences.

Commands:

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_evaluation.py' -v
PYTHONPATH=src python -m kalmora solve-ar-cash participant/phase_dev \
  --use-preparsed --normalized-dir participant/normalized_sources \
  --output /tmp/ar_cash-m4-09.jsonl
mkdir -p /tmp/submission-m4-09
cp /tmp/ar_cash-m4-09.jsonl /tmp/submission-m4-09/ar_cash.jsonl
python participant/score.py participant/phase_dev participant/phase_dev \
  /tmp/submission-m4-09
```

The detailed compare uses the evaluator's `compare_ar_cash` with the organizer scorer loaded from `participant/score.py`; the golden remains evaluation-only. In an imported package, `kalmora evaluate --evaluator <phase>` writes the complete JSON report. The unpacked local package used for this run lacks `manifest.json`, so the full CLI compare could not be invoked here; the official score and evaluator-owned AR Cash comparator were run directly and reconciled exactly.

## Issue status

Dependencies #85 and #35 are closed. The comparison contract and reproducible evaluator output are complete for M4-09.
