## Summary

Implements an isolated M6 close module and publishes simulated integration evidence
on the existing `juan-fernandez-gotherlabs:codex/m6-close` branch. This remains a
**draft for review, not full accounting or real-flow acceptance**. Target: `backend`.
No writes to main, the M5 work branch or its solver.

The branch incorporates current upstream backend through
`e448f7fd07448fe3c0b43b0605935a6f73738fac` without rewriting history. Upstream's AP
solver/evaluator-boundary fix is reused; no parallel AP correction was developed.
Implementation/tests/tools were published in `1e85d58ab63d64981017c525e24398ca3cd2a863`.
Subsequent docs/workflow evidence commits do not change the frozen accounting rules.

## Changes

- `python -m kalmora.close`: ACCRUAL, PREPAID of both signs, WIP_REVENUE,
  FX_REVAL after earlier adjustments, BAD_DEBT and declaration-month DOUBTFUL_RECLASS.
- Minimal shared CloseType extension; shared Ledger, RateTable, Evidence,
  DocumentFacts, JournalEntry/JournalLine, CloseRow and M2 certification DTOs reused.
- Sealed, phase-bound M1–M5 handoffs; full receipt coverage, semantic business-key
  and event/stage deduplication; immutable original/pre-M6/final projections.
- Explicit upstream-only `golden_fixture` adapters; original-source saved facts;
  separate evaluator reads close/balance targets only after verifying frozen output.
- Ten deterministic accounting payloads, source/output hashes, replay denying
  golden/documents/network, detailed journal/dimension and balance comparisons.
- 59 M6 regression tests, clean fork CI, reproducible commands and issue-by-issue
  status under `docs/m6/`.

## Executed evidence

Clean CI run 37127732110 on 1e85d58 (Python 3.12.14): **555 discovered, 506 passed,
49 skipped; no failures**. M6 subset: **59 passed**, also on Python 3.13.5.
Published-source fixture rebuild is byte-identical; replay against an ERP/tasks-only
phase reproduces all ten accounting payloads with zero forbidden solver accesses,
zero document calls and zero LLM calls. Earlier local optional-import failures and
the original upstream AP CI failure are retained, not described as passing.

Frozen `close.jsonl` SHA-256:
`4be0b8e740d56d26bd3810e75dc81993cdb54fc4f3fdfc98ac971cda01879810`.
The published solver fingerprint equals the pre-evaluation frozen fingerprint.
Original participant integrity: 2014 files checked, zero modifications.

## Accounting result and limitations

**Simulated integration; official close score 78.50746268656715%.**
79 rows / 70 keys versus reference 76 / 64. Actual rows: 54 ACCRUAL, 9 PREPAID,
14 FX_REVAL, 1 WIP_REVENUE and 1 BAD_DEBT. No July doubtful reclassification event;
the policy is covered by invented boundary/variation tests.

WIP, BAD_DEBT and the eight expected FX amounts are exact. Five prepaid amounts
have 1–2-cent rounding differences. Six additional historical USD credit notes
remain open under the original positions and are not removed to force row counts.
Accruals retain material estimate/coverage discrepancies, including two missing
and two extra aggregate identities. All such differences and sensitivity are
reported; no formula was calibrated after reading close targets.

Original and simulated pre-M6 account balances exactly match their reference
stages. Final balances do NOT match: M6 differences are quantified by society and
account in RESULTS.md and the detailed delivery reports. Aggregate tolerance is
not a substitute for journal/dimension acceptance. `phase_test` was not supplied;
no blind-phase success is claimed.

## Review and gate

Self-review: `docs/m6/REVIEW.md`; it is not an independent approval. Remaining
criteria: `docs/m6/ISSUES.md`. Keep M6, its epics/tasks and #171 **OPEN**. Real
M1–M5 → M6 execution with genuine producer versions/coverage has NOT been run.
No merge or issue closure is requested on simulated evidence alone.

Refs #20, #21, #22, #23, #95, #96, #97, #98, #99, #100, #101, #102, #103, #104, #171.
