# M4-01 input integration and validation

## Input boundary

The default `solve-ar-cash` path reads the phase's structured ERP and bank data and JSON notice sidecars. It does not parse an attachment. Development runs can opt into `--use-preparsed --normalized-dir participant/normalized_sources`; the document router loads the corresponding `ParsedDocument` snapshot and checks its relative path and SHA-256 against the current original. A missing, invalid, or stale snapshot is an explicit error, with no parser fallback.

Remittance tables are accepted only when beneficiary, value date, currency, total, individual amounts, and unique invoice references agree with the bank receipt. FACe contributes an invoice only when one `PAGADA` row agrees on invoice company, customer, currency, paid date, and exact receipt amount. Both sources remain corroborating evidence: open-item availability is still checked against the chronological ERP ledger before an application is emitted. Contradictory or ambiguous evidence leaves the receipt unresolved.

## Development-phase evidence

Run from the repository root:

```sh
PYTHONPATH=src python -m kalmora solve-ar-cash participant/phase_dev \
  --use-preparsed --normalized-dir participant/normalized_sources \
  --output /tmp/ar_cash.jsonl
```

The run emits 32 receipt rows: 27 applications and 5 unresolved rows. Five of six PDF remittance tables pass beneficiary/date/currency/total validation and retain the source SHA-256 in run diagnostics. `RCPT-000590` is rejected as contradictory evidence because its normalized notice says EUR while the bank receipt is MXN. The ERP invoice reference still identifies that receipt; the notice itself is not used to override the bank or ERP currency. FACe confirms the exact invoice for `BL0000581` by paid status, date, company, customer, currency, and amount.

The organizer scorer returns **0.8922** for `ar_cash` (27 of 32 fully correct). Its five incomplete rows are `BL0000201`, `BL0000276`, `BL0000544`, `BL0000567`, and `BL0000707`. They remain explicit follow-up cases for the temporal-balance, grouped-application, netting, and duplicate/overpayment issues; the source integration does not guess their application. `BL0000706` applies to `OB26-00025` from its remittance and remains separate from bank import to 555.

## Validation

- AR cash unit tests cover optional sidecars, remittance acceptance/rejection, FACe date/customer matching, source hash binding, duplicate/conflicting evidence, and balanced adjustments.
- Run the AR cash and document-router suites:

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_ar_cash*.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_document_router.py' -v
```

- Compare output with the official scorer:

```sh
mkdir -p /tmp/submission
cp /tmp/ar_cash.jsonl /tmp/submission/ar_cash.jsonl
python participant/score.py participant/phase_dev participant/phase_dev /tmp/submission
```

Do not read `golden/` from solver logic.
