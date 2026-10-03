# M4-05 evidenced penalties and AP netting

## Decision rules

A penalty can reduce a receipt only when its notice is dated on or before the bank receipt, identifies the same customer/company/currency context, and uniquely explains the amount. A notice dated later is not retrospective evidence. Any remaining cash is handled as a partial application only when the existing receivable rules identify one unique eligible item.

AP netting is evaluated against the same counterparty and company using the AP open balance as of the receipt date. A payable posted after the receipt cannot support an earlier offset. Missing or ambiguous AP evidence does not create a `NETTING_AP` residual or an invented partial difference.

## Phase evidence

The July structured ERP data contains ten penalty notices. Receipt `BL0000161` has a supported penalty of 212,795 cents on `SU26-00056`; the other application is `SU26-00035`. This is a positive phase example for the existing penalty path.

`BL0000567` remains unresolved for AP netting. The related vendor identity does not establish an open payable in the same company at the receipt date. The supplied open-items snapshot is not dated, so it cannot prove the July 6 balance. The solver abstains rather than using a later or end-of-period balance.

Regression cases ensure that a notice arriving after the receipt cannot support a penalty and that an AP posting after a receipt cannot support netting for it. In both cases, a uniquely identified receivable is treated as a partial payment; no residual difference is invented.

## Validation

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_ar_cash*.py' -v
PYTHONPATH=src python -m kalmora solve-ar-cash participant/phase_dev \
  --use-preparsed --normalized-dir participant/normalized_sources \
  --output /tmp/ar_cash-m4-05.jsonl
PYTHONPATH=src python -m kalmora evaluate participant/phase_dev \
  /tmp/submission-m4-05 --structure-only
python participant/score.py participant/phase_dev participant/phase_dev \
  /tmp/submission-m4-05
```

The AR Cash test suite passes (25 tests). The normalized-source run emits 32 rows: 27 decided and 5 unresolved. Structure validation reports no diagnostics and zero separation violations. The official evaluator reports `ar_cash = 0.8922` (27/32 fully correct), unchanged from the preceding M4 work.

## Issue status

Issue #82 depends on #80 (grouped applications) and #55 (AP export/compare); both remain open. The current July evidence also cannot establish a dated AP balance for `BL0000567`. This change hardens the evidence boundary and records the validated penalty case, but does not claim the netting acceptance criteria are complete. Keep #82 open pending those inputs and a fully supported phase result.
