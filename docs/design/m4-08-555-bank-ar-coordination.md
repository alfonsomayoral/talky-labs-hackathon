# M4-08 bank import and AR cash application

## Ownership and posting flow

`BL0000706` has two accounting stages with one owner each:

1. Bank reconciliation imports the statement movement once: Dr 57200001 / Cr 55500000 for 51,496,121 cents. Its provenance stage is `bank_import`.
2. AR Cash applies the clearing balance to `OB26-00025`: Dr 55500000 / Cr 43000000 for the same 51,496,121 cents.

The application does not touch 572 again. Together, the two entries leave 555 at zero and preserve the bank balance. `Ledger` permits these distinct stages for the same source event and rejects a repeated application stage.

The AR decision uses the normalized remittance snapshot for `OB26-00025` through `DocumentRouter(use_preparsed=True)`, which validates its source path and SHA-256. The bank movement remains owned by bank reconciliation.

## Phase validation

An integration regression runs both modules against the July phase inputs and checks the exact bank line, invoice, amounts, accounts, company and provenance stage. It then projects the bank import plus the AR adjustment through `Ledger` and asserts the 555 balance is zero, 572 is unchanged by the application, and an accidental second application is rejected.

Commands:

```sh
KALMORA_PHASE_DEV=participant/phase_dev PYTHONPATH=src \
  python -m unittest discover -s tests -p 'test_bankrec_journal.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_ar_cash*.py' -v
PYTHONPATH=src python -m kalmora solve-ar-cash participant/phase_dev \
  --use-preparsed --normalized-dir participant/normalized_sources \
  --output /tmp/ar_cash-m4-08.jsonl
PYTHONPATH=src python -m kalmora solve-bank-rec participant/phase_dev \
  --output /tmp/bank_rec-m4-08.jsonl
PYTHONPATH=src python -m kalmora evaluate participant/phase_dev \
  /tmp/submission-m4-08 --structure-only
python participant/score.py participant/phase_dev participant/phase_dev \
  /tmp/submission-m4-08
```

The integration test passes alongside the 29 AR Cash/remittance tests. The July bank-rec run emits 12 accounts, 224 matches and 59 adjustments. The combined submission passes structure validation with no diagnostics and zero separation violations. Official scores: `ar_cash = 0.8922` (27/32 fully correct), `bank_rec = 0.9951`.

## Issue status

Issue #85 depends on #81 and #82, both still open; #83, #84, and #75 are closed. The BL0000706 ownership and 555 flow are validated, but keep #85 open until its remaining dependencies are resolved and the integrated result is revalidated.
