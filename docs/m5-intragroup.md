# M5 intercompany module — isolated dependency validation

Refs #18, #19, #88, #89, #90, #91, #92, #93, #94, #159.

## Scope and boundaries

`kalmora.ic` reuses `PhaseData`, `Ledger`, `RateTable`, `Evidence`, `validate_entry`
and `RunRecorder`. It does not implement AP, banks, extraction, LLMs or the shared
#35 comparator. It never reads reference files. Main is not a delivery target.

Positions retain company/account/raw partner/assignment, local cents, document
amounts, comparable EUR cents and original book-line evidence. Master-backed
V-IC aliases are not inferred by removing prefixes. Invoice, pooling/interest,
loan and UTE accounts remain separate. There is no 50% UTE consolidation output.

The ERP is immutable. Snapshots distinguish recorded, before IC and corrected
positions. `Ledger.project()` and explicit event/stage owners prevent repeat
posting. A prior projection must contain every original entry unchanged.

## Contracts

`reconcile(data, recorded=ledger, upstream=Upstream(...))` consumes:

- `ap_entries`: explicit `OwnedEntry(event_id, stage, entry, evidence)` objects.
  An absent delivery is `None`, not a fabricated empty success.
- `ap_coverage`: `ReceiptCoverage(month, complete, receipts, producer, evidence,
  unresolved_documents)`. Every received invoice counts, including HOLD, REJECT,
  DUPLICATE and unposted documents. A `Receipt` contains company, issuer,
  reference, received_on and evidence. An explicitly unknown issuer (`None`)
  is a possible match by company/reference and blocks an absence inference for
  that reference. Missing recipient/reference/date prevents complete coverage.
- `banks`: `BankDelivery(producer, complete, entries, pooling_links, evidence)`.
  A pooling link maps an original statement ID to the bank entry's event/stage.
- `prior_projection`: optional full append-only Ledger, never a replacement ERP.
- `invoice_allocations`, `interest_allocations`: explicit supported allocations
  where unique historical evidence is insufficient.
- `valuation_entry_ids`: optional explicitly identified local-only FX entries.
- `provenance`: producer/source metadata, including `golden_fixture` when used.

The JSON adapter is `load_upstream(path)`, schema_version 1. It accepts the same
contracts for real and simulated producers. A producer declaration does not
prove that the real pipeline has run. `complete` means the modular inputs and
rules have no blocking diagnostics, **not** exact reference acceptance or M5
closure. The audit and run record separately retain integration_mode and
real_flow_verified=false; #159 is the real-flow gate.

## Rules and ownership

Invoice nonreceipt needs complete receipt coverage, not merely absence from the
journal. Net expense, supported receiver allocation and invoice-date FX determine
Dr expense / Cr 40090000 with the issuer company. Reported difference and expense
can differ by VAT. Existing accruals, including earlier periods, are recognized;
partial/conflicting accruals are not overwritten.

Interest uses supplied principal, basis points, dates and actual calendar days
on act/360, independently for both parties. Comparison EUR and local MXN postings
are distinct. Known local-only revaluation never changes document principal.

Wrong trading partner requires a unique compatible opposite mirror. The signed
reported amount is the residual left in the intended pair (debit minus credit
in EUR), not the absolute size of the misplaced posting. Reclassification adds
the opposite leg. Tests cover both cash directions, both company orientations
and a local-MXN/document-EUR case without any July-specific sign rule.

A duplicate reverses the whole posting, including taxes, assignments and CC/WBS.
An exact AP/bank-owned reversal or partner reclassification already projected
is consumed once, without an additional M5 journal. Partial or excess external
corrections block resolution; ownership alone does not prove a correction.
Pooling is observed in the original ERP, tied to its statement and consumed bank
correction, but always has `adjustment: []` in IC. Its owner remains banks.

## Authorized fixture adapter (#159)

`tools/m5_fixture.py` is a separate development/evaluation-side adapter. Its only
readable reference members are `phase_dev/golden/ap.jsonl` and
`phase_dev/golden/bank_rec.jsonl`. It cannot read IC expected output. It verifies
source files against the unchanged original ZIP and records the actual members
opened, SHA-256 values, phase, month, coverage and producer provenance.

AP receipt coverage reconciles the exact task, result and message ID sets.
Every message date must exist; there is no fallback to an invoice date. Historical
AP log receipts are also retained. Coverage is independent of projection scope.
For July this means all 305 tasks/results/messages, 141 historical IC receipts,
7 current identified IC receipts and 2 explicitly unknown-issuer receipts.

The explicit `--ap-projection-scope intercompany` projects all 6 IC-relevant
entries from 242 posted AP fixtures. The other 236 are inventoried as out of
scope, not silently claimed as posted. `full` scope is supported but rejects
invalid reference entries: the current non-IC advance line with missing partner
is not repaired, excused or smuggled into M5. This is not a full AP engine test.
All 12 bank accounts and all 56 supplied bank corrections are consumed.

The pooling link comes from the bank unmatched ID, signed amount/currency,
agreement and unique same-date opposite ERP mirror. The projection header uses
that independently supported mirror reference. The original bank fixture ref is
retained in evidence. No IC reference supplies the link. Original line dimensions
are copied; missing document dimensions in flat bank output are not fabricated.

## Reproduction

Use a separate checkout of the M5 branch and Python >=3.12:

```bash
python -m pip install -e .
python -m compileall -q src tools
python -m unittest discover -s tests -v
kalmora doctor
git diff --check
python tools/m5_prepare_inputs.py --package /path/participant.zip --out /tmp/m5-inputs
python tools/m5_fixture.py --package /path/participant.zip \
  --phase /tmp/m5-inputs/participant/phase_dev --out /tmp/m5-fixtures \
  --ap-projection-scope intercompany
python tools/m5_run_isolated.py --phase /tmp/m5-inputs/participant/phase_dev \
  --upstream /tmp/m5-fixtures/upstream.json --out /tmp/m5-isolated \
  --backend-commit "$(git merge-base HEAD upstream/backend)" --check-replay
```

The isolated process installs an open-audit guard before importing M5. ZIP,
reference and evaluator reads are denied, including symlinks; a denied probe
confirms the guard is active. Fresh repeated runs must have identical IC bytes.
Replaying on the corrected projection emits no further IC corrections and keeps
the projected ledger unchanged. The original ERP hash is conserved throughout.

Standalone production-style invocation remains `python -m kalmora.ic --phase ...
--out ... --upstream ... --backend-commit ...`. `--recorded-only` explicitly
acknowledges missing dependencies and exits 3. The output includes `ic.jsonl`,
audit snapshots, producer-owned projection delta and RunRecorder metadata.

## Evaluation and closure

Freeze source and `ic.jsonl` hashes before evaluating. The separate
`tools/m5_evaluate.py` consumes the actual shared `compare_ic`/`load_scorer` APIs,
runs the original scorer unchanged and checks signed amount, pair, responsible,
company, accounting lines and reference-provided assignment/tax/currency fields.
Use `--require-shared`. IC expected data is never fed back as solver input.

Current simulated output matches all fields of all 5 reference rows, including
the repaired sign and the net transit accrual. It also reports 3 additional
source-supported nonreceived invoices. Therefore it contains 8 rows / 7 IC
entries and scores 0.8615; **exact acceptance is not proven**. The extra rows
are not suppressed using the reference answer. See `m5-review.md`.
The reproduced checks and external-correction regression fix are recorded in
`m5-independent-review.md`.

M5, both epics and #159 stay open. Real AP receipt coverage, real bank correction
ownership and the real end-to-end run remain separate gates. Publication and
unit tests do not substitute for them. PRs target upstream backend with English
text and Refs; review and checks precede any squash merge.
