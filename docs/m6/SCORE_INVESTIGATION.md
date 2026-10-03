# M6 score investigation — 3 October 2026

M6 remains **simulated integration**. Implementation tracking #20–#23 and
#95–#104 was closed at the user's request, with unresolved accounting work
consolidated in #251. The final real-flow/no-golden/September acceptance is #171.
Neither this score change nor a replay of fixture-built facts closes that gate.

The code is also published directly in
`alfonsomayoral/talky-labs-hackathon:codex/m6-close`. The same fork head continues
to update the existing draft PR #197; no duplicate PR is created. The M6 CI now
runs in both repositories.

## Reproduced baseline and source changes

The original `participant.zip` SHA-256 is
`c813449eab9ddc7fc28b04eff85518957035e895b5500fd19e26c0d8ef7f0109`.
On the original `7216a0b` source, rebuilding the fixture reproduced the published
handoff payload and the exact `close.jsonl` hash, not merely its score.
Backend `e1c22c0` was merged before the changes; the branch was then refreshed
through `bf7943ffa9c6572b8d936c701b4ee7f855015488` without rewriting history.

Two source-handling corrections are retained:

1. Separate invoice business identities with identical service periods and cost
   objects contribute additive costs. The previous dictionary assignment discarded
   all but the last sample. Historical estimates are first reduced to the latest
   closing for the same obligation reference and service interval: a reversal and
   reissue is not new consumption. Distinct obligations remain additive.
   Actual posted costs replace a historical estimate for
   the same interval; the last-three-period median remains in place. Financial
   samples require POST/POST_PAYMENT_BLOCK, while receipt coverage retains every
   status. A rejected first arrival cannot hide the later posted correction.
2. A professional's separate one-day historical jobs do not prove a new month's
   consumption. Monthly exposure requires at least two distinct observed full-month
   service periods. This is a conservative evidence assumption, not a literal
   policy threshold. Otherwise the adapter retains an explicit unknown-consumption
   diagnostic instead of inventing a monthly accrual.

These rules contain no supplier identities, expected closing amounts, or target
row counts. Synthetic cases cover both corrections independently of organizer data.
The close engine, policy amounts, evaluator, source inputs, and FX positions are
unchanged. The source adapter continues to be a development fixture adapter;
real-provider acceptance remains separate.

## Experiments

Each output was frozen before the separate evaluator opened closing targets.
The invoice-priority experiment was rejected; it is not the shipped estimator.

| Run | Close score | Rows / keys | Interpretation |
|---|---:|---:|---|
| Reproduced original baseline | 78.50746268656715% | 79 / 70 | Published hash reproduced exactly |
| Prefer posted invoices over all historical estimates | 77.91044776119403% | 79 / 70 | Rejected; unreliable as a universal forecasting change |
| Sum same-period costs, preserve median | 78.50746268656715% | 79 / 70 | Fix retained; no component-score increase by itself |
| Also preserve unknown discrete professional consumption | **79.09774436090226%** | **78 / 69** | Removes one unsupported accrual key |
| Deduplicate reissued historical obligations after team review | **79.09774436090226%** | **78 / 69** | Retained source correction; component score unchanged |

The gain is **0.59028167433511 percentage points in close**, not the total challenge
score. Recall remains 0.822; precision rises from 0.751 to 0.762. No missing service
identity has been recovered. The final output has 53 accrual rows / 44 keys versus
57 / 45 in the reference. Two expected identities and one extra identity remain.
The six additional FX positions and the small prepaid rounding differences remain.

## Balance tradeoff

The account-level original and pre-M6 differences remain zero. Final balances still
do not match. Eliminating an unsupported accrual also removes an accidental account
offset against other missing/underestimated expenses. Do not describe the score
increase as a general balance improvement.

| Company | Currency | Original baseline absolute account difference | Final difference |
|---|---|---:|---:|
| 1000 | EUR | 76,005.86 | 82,806.94 |
| 1100 | EUR | 6,991.20 | 6,958.08 |

Other companies' account differences are unchanged. These are two-sided sums of
absolute account differences, not losses or cash flows. EUR and MXN are separate.

## Evidence and remaining work

Local Python 3.12.4 validation after refreshing backend: **879 discovered,
815 passed, 64 skipped; no failures**. The M6 subset has **66 passing tests**.
A fresh-process replay in a physical ERP/tasks-only phase reproduces all ten
accounting files, with zero forbidden accesses, document calls and LLM calls.
All 830 imported original-package files match their manifest hashes.

Source CI on `95cd046` passed in both repositories. Python 3.12.14: **66 M6
tests pass; 879 backend tests discovered, 839 passed, 40 skipped, no failures**;
compile and the actual CLI doctor also pass. Downloaded upstream CI evidence
contains the exact retained source adapter.
[Upstream CI](https://github.com/alfonsomayoral/talky-labs-hackathon/actions/runs/37131128321),
[fork CI](https://github.com/juan-fernandez-gotherlabs/talky-labs-hackathon/actions/runs/37131153914).
The subsequent delivery commit contains only documentation/evidence.

Final close SHA-256:
`8f062c48fc8951f4462b07f67cb3d0d3dd33e4d22e0fefd1d05589c9637562e9`.
Scorer SHA-256 remains
`b8adec99c609098c7781b4d34cd08ddd6c7d62830800ac9b37d5b1213ca0828e`.
The machine report is `evidence/score-investigation.json`. Frozen handoffs, outputs,
evaluation detail, and rejected-experiment evidence remain under
`outputs/m6-score/{baseline,candidate,merged,final,reviewed}` in the task worktree.
The `reviewed` run is the retained final output; `final` preserves the earlier
professional-guard experiment before historical-obligation deduplication.

Three parallel source/code reviews are saved under `reviews/`: accrual evidence,
foreign credit-note evidence, and the source-change review. They identified the
reissued-estimate defect before publication. The two missing service series have
no observed current consumption; their old May invoices were received in June.
The market-representation series has monthly invoice history but no explicit
exclusion from accruals. The six USD credit notes are explicitly open in the ERP
and have no clearing under their assignments. None of these discrepancies is
removed by inserting provider-specific evaluation knowledge. Team review does
not constitute maintainer approval or real-flow acceptance.

The next useful work in #251 is to obtain positive evidence of current service
consumption, review the two missing series and cost-object coverage, and establish
whether the historical foreign credit notes were compensated. Do not remove FX
positions merely because the reference omits them. Do not select provider-specific
multipliers from the evaluation amounts. #171 additionally requires actual M1–M5
deliveries and the blind September phase with no golden-derived dependencies.
