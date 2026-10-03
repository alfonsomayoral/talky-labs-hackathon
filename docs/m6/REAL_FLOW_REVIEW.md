# Real AP → banks → IC → M6 review — 2026-10-03

The deterministic workflow now consumes actual outputs from the v0 AP engine,
bank reconciliation, AR billing/cash and IC. IC no longer runs recorded-only.
M6 requires a phase-bound IC audit of every configured pair, verified source and
delivery hashes, and the exact producer-owned AP/bank/IC postings. An incomplete,
stale or empty exception report cannot prove successful integration.

Implementation was executed at `575e2409ba401053eadbf910e83afe81c3705c98`,
rebased on backend `0840e539520e3ea5dbb3fec9d89f3ba8b5cb6da9`.
PRs #197 and #277 remain merged. Issues #171, #251, #159 and milestone M6
remain open for review; operational integration is not accounting acceptance.

## Changes

- Reuse one AP receipt/bank ownership adapter for real and explicit fixture
  inputs. The fixture loader remains outside the accounting solver.
- Preserve all AP receipt decisions and independently observed service periods.
  Non-posting invoices can retain factual line allocations without a journal.
  Ambiguous receipt allocation blocks its historical service series.
- Project the same canonical AP/bank entries into IC and M6. Verify pooling
  against original statement ID, signed amount/currency and unique ERP mirror.
  IC emits no second pooling entry.
- Persist IC inputs, positive coverage, audit and owned delta, plus the sealed
  M6 handoff and frozen outputs. Missing/incomplete/failed modules keep `ok=false`;
  repeated runs discard stale deliveries and audits.
- Preserve open foreign supplier credit notes as signed monetary positions
  under policy §5. No clearing source supports removing the six historical USD
  items reviewed in [fx-evidence.md](reviews/fx-evidence.md).
- Omit absent non-nullable optional AP fields and retain the vendor on 407
  advance lines. These metadata corrections preserve accounting cents.

## Executed evidence

| Result | July development | September blind phase |
|---|---:|---:|
| Actual AP task/result/message IDs | 305 / 305 / 305 | 297 / 297 / 297 |
| Billing / bank accounts / cash tasks | 26 / 12 / 32 | 25 / 12 / 34 |
| IC findings / blocking diagnostics | 8 / 0 | 8 / 0 |
| M6 rows | 77 | 84 |
| Full workflow | All six modules done | All six modules done |
| M6 saved-fact replay | 10 accounting files identical | 10 accounting files identical |
| Official global score | 96.79% | Unavailable |

July M6 is **82.7273%** and IC is **86.1538%**. All five IC reference
entities match exactly, including unscored dimensions; the three additional
source-backed transits accepted under #239 remain visible. M6 retains six extra
USD credit-note valuations; improving the score by excluding them would conflict
with the available open-item evidence. The score decrease relative to #277 is
reported, not hidden.

July still has four AP company mismatches against the reference:
API005209, API005225, API005226 and API005227 (five diagnostics because the last
also affects its journal). Review their original recipient evidence in the AP
workflow before treating #171 as accepted. The reference's missing 407 partner
is recorded separately; real delivery lines now carry that required vendor.
September passes shared structure validation with no diagnostics. No September
golden or official score is claimed.

Current-backend suite: **1,246 discovered; 1,203 passed; 43 optional-data/service
skips; zero failures** on Python 3.12.2. Compile, doctor and diff checks passed.
IC replay on the corrected projection retains the exact corrected ledger hash,
eight findings and zero new adjustment lines. Four negative probes reject an
incomplete audit, missing pair, empty IC output and changed AP delivery.

The solving processes denied Python access to golden and trial balances. July's
817 non-reference inputs were byte-compared with the original package. M6 replay
also denied inbox/bank reads, evaluator/adapter imports and network; it made zero
document/model calls and zero forbidden accesses. These are guards for this
Python workflow, not a sandbox for hostile native code.

Machine evidence: [real-flow-20261003.json](evidence/real-flow-20261003.json).
Full frozen runs, audit/projection/replay and evaluation logs are preserved
locally in `outputs/m6-real-flow-20261003/`; original datasets are not modified.

## Reproduce

Use the unchanged July participant package or extract the original September
package. Use a distinct output directory outside the phase.

```bash
python -m pip install -c requirements-m1.lock -e '.[documents,llm,landing,api,dev]'
export KALMORA_SOURCE_PHASE=/absolute/path/to/participant/phase_dev
export PYTHONPATH=src:tools/close_verify_guard
python -m kalmora close "$KALMORA_SOURCE_PHASE" --out /absolute/path/to/run

# Separate fresh-process replay of frozen facts.
PYTHONPATH=src python tools/m6_replay.py --phase "$KALMORA_SOURCE_PHASE" \
  --handoff /absolute/path/to/run/handoffs/close/dependencies.json \
  --expected /absolute/path/to/run/handoffs/close/frozen \
  --output /absolute/path/to/run/replay

# Only the separate evaluator may access the development reference.
PYTHONPATH=src python -m kalmora evaluate "$KALMORA_SOURCE_PHASE" \
  /absolute/path/to/run/deliverables --evaluator "$KALMORA_SOURCE_PHASE" \
  --report-dir /absolute/path/to/run/evaluation
```

For September, replace the phase and output directory and use
`--structure-only` without `--evaluator`. Historical simulated results remain
in RESULTS.md and SCORE_INVESTIGATION.md. Further closure requires review of
the remaining AP/source/reference differences; neither a high score nor
`engine_data_complete` proves universal documentary correctness.

