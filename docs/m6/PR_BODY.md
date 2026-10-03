## Summary

Adds the M6 month-end close module to `backend`, with sealed M1–M5 handoffs,
original/pre-close/final ledger projections, and a separate frozen-output evaluator.
This draft now also fixes source-cost aggregation and unsupported professional
extrapolation. The same commits are published directly on the upstream
`codex/m6-close` branch; this existing PR retains its original fork head.

The branch incorporates upstream backend through
`bf7943ffa9c6572b8d936c701b4ee7f855015488` without rewriting history.

## Behavior

- Supports ACCRUAL, signed PREPAID, WIP_REVENUE, FX_REVAL, BAD_DEBT and
  declaration-month DOUBTFUL_RECLASS using the shared ledger, money, evidence,
  journal and certification contracts. Entries are month-end only and retain
  supplier/customer, account and cost-object dimensions.
- Requires complete phase-bound producer coverage and deduplicates business
  identities and event/stage ownership. Original ERP data remains immutable.
- Keeps independent posted invoice costs additive within their service interval.
  Reissued historical estimates retain only the latest closing per obligation;
  actual costs replace estimates for the same period. The historical median remains.
- Treats isolated professional jobs as unknown additional consumption rather than
  inventing a full new month. Repeated full-month history is an explicit conservative
  evidence assumption, not a policy threshold.
- Enables the existing M6 CI job in both the upstream repository and fork.

## Result and validation

The original July baseline is byte-for-byte reproduced. After freezing the new
output and evaluating separately, the **close component rises from 78.50746% to
79.09774% (+0.59028 percentage points)**. Output is 78 rows / 69 keys, versus
76 / 64 in the reference. Recall is unchanged; one unsupported accrual key was
removed. No missing key was recovered. This is simulated integration, not the
whole-challenge score or real-flow acceptance.

The original and pre-M6 account balances match their reference stages. Final
balances still differ: company 1000's two-sided absolute account difference
worsens from EUR 76,005.86 to EUR 82,806.94; company 1100 improves from EUR 6,991.20
to EUR 6,958.08. Currency amounts are not combined. Six original open USD credit
notes remain because source review found no clearing evidence. Accrual coverage
and small prepaid rounding discrepancies remain documented.

Local Python 3.12.4: 66 M6 tests pass; full backend has 815 passes and
64 skips (879 discovered), with no failures. Source CI on `95cd046` is green
in both repositories: Python 3.12.14, 66 M6 passes and 839 backend passes /
40 skips. [Upstream run](https://github.com/alfonsomayoral/talky-labs-hackathon/actions/runs/37131128321),
[fork run](https://github.com/juan-fernandez-gotherlabs/talky-labs-hackathon/actions/runs/37131153914).
Full results are recorded in `docs/m6/evidence/score-investigation.json`. A fresh-process replay
against a physical ERP/tasks-only phase reproduces all ten accounting files,
with zero forbidden accesses, document calls or LLM calls. Its handoff was built
from authorized development fixtures; replay does not prove real M1–M5 execution.

Frozen close SHA-256:
`8f062c48fc8951f4462b07f67cb3d0d3dd33e4d22e0fefd1d05589c9637562e9`.
The imported original package has 830 verified files and zero modifications.
Three parallel team reviews, source evidence and rejected forecasting experiment
are documented in `docs/m6/SCORE_INVESTIGATION.md` and `docs/m6/reviews/`.

## Remaining acceptance

At the user's request, fourteen modular tracking issues were closed; unresolved
scope from superseded items is consolidated in **#251 (score/accounting work)**.
**#171 stays open** for actual M1–M5 producers with no golden-derived dependencies,
physical golden exclusion, September execution, rerun/ownership evidence and
reviewed accounting output. September originals are available; this real-flow
execution has not been completed. The milestone and draft remain open.

Refs #20, #21, #22, #23, #95, #96, #97, #98, #99, #100, #101, #102, #103, #104,
#171, #251.
