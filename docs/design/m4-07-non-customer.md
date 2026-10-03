# M4-07 non-customer receipts

## Classification rules

When no customer can be identified, classify only explicit non-customer descriptions covered by policy §3.2:

- VAT refund (`IVA` plus a refund/return term): credit 47000000.
- Bond return (`FIANZA`, or a deposit explicitly described as a guarantee): credit 56500000.
- Insurance indemnity (`INDEMNIZACION`, or an insurer description): credit 75900000.

The output keeps `customer: null`, emits `NON_CUSTOMER`, and balances the already-posted Dr 572 / Cr 555 against the policy account. The classifier uses whole normalized words; “seguros sociales” alone is not evidence of an insurance recovery. Ambiguous descriptions remain unresolved.

## Phase evidence

July task `BL0004434` is a 408,707-cent transfer described as a Portuguese tax authority VAT refund for period 2026-05. It is classified with `customer: null`, residual `NON_CUSTOMER`, and adjustment account 47000000. This is the phase example. The July task set has no insurance-indemnity or bond-return receipt, so those branches are validated with synthetic tests only.

Tests cover the VAT refund, a returned construction bond, an insurance indemnity, and a negative “seguros sociales” description. They verify the residual, null customer, and balancing account.

## Validation

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_ar_cash*.py' -v
PYTHONPATH=src python -m kalmora solve-ar-cash participant/phase_dev \
  --use-preparsed --normalized-dir participant/normalized_sources \
  --output /tmp/ar_cash-m4-07.jsonl
PYTHONPATH=src python -m kalmora evaluate participant/phase_dev \
  /tmp/submission-m4-07 --structure-only
python participant/score.py participant/phase_dev participant/phase_dev \
  /tmp/submission-m4-07
```

The AR Cash and remittance suites pass (29 tests). The normalized-source run emits 32 rows: 27 decided and 5 unresolved. Structure validation reports no diagnostics and zero separation violations. The official evaluator reports `ar_cash = 0.8922` (27/32 fully correct), unchanged.

## Issue status

Issue #84 depends on #78 (closed) and #80 (still open). The NON_CUSTOMER behavior and phase comparison are complete, but keep #84 open until the listed #80 dependency is resolved and the M4 result is revalidated.
