# M5 — Intercompany reconciliation

Refs #18, #19, #88, #89, #90, #91, #92, #93, #94. This implementation does **not** close these issues by itself.

## Boundary and accounting model

`kalmora.ic` is an independent Python module. It consumes the existing `PhaseData`,
`Ledger`, `RateTable`, `Evidence`, `validate_entry`, and `RunRecorder`. It does not
replace their models, edit the shared CLI, implement document extraction, or own
AP/bank/scorer work. It uses no LLM, third-party dependency, or database engine.

The original ERP is immutable. The module produces three position snapshots:
recorded, before IC (with actual caller-supplied deliveries), and corrected. Each
keeps company/account/raw partner/assignment separate, while a second index maps
master-backed partner aliases to company pairs. Source `id#line` references remain
in the audit. EUR comparison and local ledger amounts are distinct quantities.
Known local-only FX revaluations do not change foreign loan principal. An external
UTE partner is excluded from task pairs; no 50% consolidation is generated.

`reconcile(data, recorded=ledger, upstream=Upstream(...))` returns findings,
diagnostics, an independent projected Ledger, snapshots, and lineage. A missing
interface stays `None`; the audit is incomplete rather than fabricated. An
explicit empty producer delivery is different from a missing one. A prior
projection, when provided, must contain all original entries byte-for-byte after
shared Ledger normalization, and every added entry must have producer ownership.
When omitted, the baseline is explicitly the recorded ledger, not an assertion
that another engine has completed its work.

## Rules

| Issue | Implementation | Evidence and safety behavior |
| --- | --- | --- |
| #88 | `positions.py` | 433/403/400900, 552, 2423/1633, 5521/5522; aliases only from active masters; raw keys and book references retained. |
| #89 | `positions.py`, `calculation.py` | EUR document amounts, exact Decimal/RateTable conversion, local MXN projection, FX valuation separated. |
| #90 | `invoices.py` | Complete AP receipt coverage is required to infer nonreceipt. Expense uses issued net, never VAT-inclusive gross; invoice-date FX; explicit or uniquely evidenced historical cost allocation; 400900 counterparty is issuer company. |
| #91 | `interest.py` | Supplied principal/rate/start/end, actual calendar days/360, both parties checked independently, comparison EUR versus local correction. No hardcoded phase or amount. |
| #92 | `corrections.py` | Unique compatible mirror for wrong partner; full duplicate reversal including taxes, assignment and cost objects. Same reference with conflicting financial contents is blocked; FX revaluations are excluded. |
| #93 | `pooling.py` | Detect missing original ERP side and match the actual statement. Link an explicit bank-owned correction; IC always emits no pooling journal. |
| #94 | `engine.py`, standalone CLI, evaluation tool | Organizer JSONL fields plus audit; optional shared contract validator hook, separate evaluation of all required fields. |

Invoice decisions run after reclassification, so a wrong-party invoice does not
also cause an in-transit accrual. Existing accruals, including carried prior-month
accruals, are checked for amount and allocation. Conflicting partial accruals are
left to their owner, not overwritten. Existing external interest corrections are
recognized; partial/conflicting corrections remain explicit blockers. An interest
posting with the wrong partner is not interpreted as zero numeric accrual.

The existing shared validator requires a cost object for lender account 76210000.
When the lender needs adjustment, the caller must provide a supported allocation;
M5 does not weaken that validator. Each generated entry is balanced and validated
against company, account, partner and cost-object masters.

## AP, bank and projection hand-off

The public input dataclasses live in `model.py` (inside the M5 package, not a
replacement for the shared data model). The JSON adapter is `load_upstream(path)`.
It only decodes producer facts; it never runs their engines. Its schema is:

```json
{
  "schema_version": 1,
  "prior_projection": null,
  "ap_entries": null,
  "ap_coverage": null,
  "banks": null,
  "invoice_allocations": [],
  "interest_allocations": {},
  "valuation_entry_ids": []
}
```

Null entries are intentionally **not a completed example**. The providers must
supply the following real information before integration can pass:

* `prior_projection`: optional path to a full append-only JSONL ledger, resolved
  relative to the manifest, including shared `provenance: {event_id, stage}`.
* `ap_entries`: list of `{event_id, stage, entry, evidence}` from #55. `entry` is
  the normal shared Ledger journal shape; `evidence` is the shared Evidence
  shape `{document, field, page?, quote?}`.
* `ap_coverage`: `{month, complete, producer, evidence, receipts,
  unresolved_documents}`. Each receipt has `{company, issuer, reference,
  received_on, evidence}`. The AP owner certifies a complete IC receipt inventory
  through close, not merely successfully posted invoices. Receipts may be held
  or rejected by AP but still prove that an invoice was received. Unresolved
  documents prevent `complete=true`; company/issuer are group company codes.
* `banks`: `{producer, complete, evidence, entries, pooling_links}`. Entries use
  the owned-entry shape above. `pooling_links` maps original statement line ID to
  `[event_id, stage]` of a supplied bank entry. M5 checks its projection,
  responsible company, partner, bank account and amount before marking resolved.
* `invoice_allocations`: list of `{issuer, receiver, reference, account,
  cost_center, wbs, evidence}`. Expense account and one appropriate cost object
  are required. Mixed historical allocations are not resolved by guessing.
* `interest_allocations`: company-to-`{account, cost_center, wbs, evidence}` map.
* `valuation_entry_ids`: optional explicit IDs of upstream local-only FX entries
  whose source enum differs from existing `CLOSE_FX` / `FX_REVAL` conventions.

The existing reader rejects `golden` paths and symlink escapes. Source documents
remain original and can live in a different read-only tree. Missing AP coverage
prevents #90 output; missing bank correction keeps the original pooling finding
with an empty adjustment and a diagnostic naming the statement and owner issues.

`contract_validator(record) -> list[str]`, when supplied to `reconcile`, consumes
the shared output validator without implementing #32. Without it, M5 serializes
the organizer's existing five IC fields and always uses shared accounting
validation. #32's owner proposed using the organizer format directly; that is not
represented here as an already-closed issue. The #35 shared comparison hook is
an evaluation-time integration, not a solver import or a replacement scorer.

## Reproducible commands

Run in an independent checkout based on `backend`, never in another agent's
working directory. Python >=3.12 is required by the repository.

```bash
python -m pip install -e . --no-build-isolation
python -m compileall -q src
python -m unittest discover -s tests -v
kalmora doctor
git diff --check
```

Use a solver-only extraction of the original package (no reference directory or
scorer). The delivery includes a preparation script. The original archive is
never changed. Its bytes may be hashed for lineage, not read for decisions.

```bash
python tools/m5_prepare_inputs.py --package /path/participant.zip --out /tmp/m5-inputs
python -m kalmora.ic \
  --phase /tmp/m5-inputs/participant/phase_dev \
  --out /tmp/m5-output --recorded-only \
  --package /path/participant.zip \
  --backend-commit "$(git rev-parse origin/backend)"
```

Exit **3** means incomplete external integration, not a successful milestone.
The partial output and diagnostics are still written. Replace `--recorded-only`
with `--upstream /path/actual-producer-deliveries.json` for the integrated run.
`--write-projection` additionally writes the full corrected journal. Default
outputs are `ic.jsonl`, `audit.json`, `projection.adjustments.jsonl`, and `runs/`.
The delta includes externally owned entries as well as IC entries; do not apply
that delta on top of a ledger that already contains them without shared ownership
checks. Replay against a prior IC projection emits no second adjustment; fresh
runs against the same original inputs reproduce the same complete proposed delta.

For real solver-input integration:

```bash
KALMORA_IC_PHASE=/tmp/m5-inputs/participant/phase_dev \
  python -m unittest discover -s tests -p test_ic_real.py -v
```

## Evaluation and delivery gates

Freeze solver code and output hashes before evaluating. Only the separate
`tools/m5_evaluate.py` evaluation process opens the original scorer/reference.
It reports original IC metrics and independently checks pair, cause, amount,
responsible, journal company/account/partner/cost object and cents. This is an M5
supplement, not a new shared scorer. The #35 output may be consumed as an explicit,
hash-bound shared report when that producer is available.

The optional pre-existing organizer validation test also belongs to evaluation:

```bash
KALMORA_PARTICIPANT_ZIP=/path/participant.zip \
  python -m unittest discover -s tests -v
```

Synthetic cases prove local interfaces and edge cases, not actual AP/bank
completion. Keep tasks/epics/milestone open until real dependencies and all output
fields meet their acceptance criteria. PRs target `backend`, use English text
and `Refs` while incomplete. Review and CI precede squash merge. No remote write,
review, merge, or CI success may be inferred from local tests.

## Live integration update (2026-10-03)

Remote `backend` advanced to `292bd0b7bac5b5c7e337452a77f9b4c0e75acd81`
while M5 was being implemented. #32 is now deprecated/closed and the shared #35
comparator is integrated/closed. The earlier dependency discussion above describes
input boundaries, not the latest GitHub state.

The current `IcRow.adjustment` type reuses `JournalLine`. Serialization therefore
preserves existing `assignment`, `tax_code`, `currency` and `amount_doc` dimensions,
in addition to company/account/debit/credit/partner/cost objects. Internal journal
IDs and source-book references remain in the audit, not in the submission.

The separate evaluator imports the actual
`kalmora.evaluation.compare.compare_ic` and
`kalmora.evaluation.scorer.load_scorer` interfaces when available. Use
`--require-shared` on the current backend to make their absence a hard error:

```bash
python tools/m5_evaluate.py \
  --package /path/participant.zip \
  --participant-phase /tmp/m5-inputs/participant/phase_dev \
  --submission /tmp/m5-output --out /tmp/m5-evaluation \
  --freeze /path/solver-freeze.json --require-shared
```

The loader verifies the unchanged scorer against a manifest hash read from the
original archive. The report records the shared modules' Git blob hashes and
reconciles their result with the independently invoked organizer CLI. An existing
native #35 report can alternatively be supplied through `--shared-report`; its
`provenance.submission_sha256["ic.jsonl"]` must match this exact submission.

The supplemental audit additionally compares every line's company and source
assignment dimensions, and does not equate the official score with acceptance.
Known remaining findings and exact execution scope are in `m5-review.md`.
