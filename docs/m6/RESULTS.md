# July M6 evaluation — simulated integration, not acceptance

This report preserves the original frozen **78.507% baseline**. The current source
corrections, **79.0977%** result and balance tradeoff are in `SCORE_INVESTIGATION.md`.

## Frozen run

The original output was frozen at **2026-10-03T13:28:42.739651Z**, before the
separate close-target evaluation. The same solver bytes were subsequently
published and verified in commit `1e85d58ab63d64981017c525e24398ca3cd2a863`, which
includes backend `e448f7fd07448fe3c0b43b0605935a6f73738fac`.
Rebuilding the dependency fixture from that exact published source produces the
same bytes. Replaying against a physical ERP/tasks-only phase reproduces all ten
accounting payload files. No new document/LLM/network calls occur in the solver.

| Identity | SHA-256 |
|---|---|
| close.jsonl | `4be0b8e740d56d26bd3810e75dc81993cdb54fc4f3fdfc98ac971cda01879810` |
| Sealed handoff payload | `7ce3769988c91f5e6da77692df692fb3e9b7bd9972dca896a58ff38a04dfa755` |
| Handoff file bytes | `712d4fa9cc73f91e4e7340e47928df5e5a1da0b5549c7741337f0ea8c623c1d6` |
| Solver source fingerprint | `9f2933dde5e9f5398ec33886cc973d0b3e49583df673a8501ce496e55eaf5931` |
| Original freeze manifest | `1e3aa41872a09e3fbb761d6ed8d5175cfb6d12407c379e1c7c052b30614349f8` |
| Organizer scorer | `b8adec99c609098c7781b4d34cd08ddd6c7d62830800ac9b37d5b1213ca0828e` |

Context manifest verification: 160/160 files unchanged. Participant integrity:
2014/2014 original archive members unchanged. No ERP/inbox/tasks/golden mutation.

## Comparison

Official close score: **0.7850746268656715 (78.50746268656715%)**.
The scorer reports 64 expected aggregate items, recall 0.822 and precision 0.751.
This is not a full pass and is not real integration acceptance.

| Type | Reference rows | Actual rows | Reference keys | Actual keys |
|---|---:|---:|---:|---:|
| ACCRUAL | 57 | 54 | 45 | 45 |
| PREPAID | 9 | 9 | 9 | 9 |
| WIP_REVENUE | 1 | 1 | 1 | 1 |
| FX_REVAL | 8 | 14 | 8 | 14 |
| BAD_DEBT | 1 | 1 | 1 | 1 |
| DOUBTFUL_RECLASS | 0 | 0 | 0 | 0 |
| Total | 76 | 79 | 64 | 70 |

The equal ACCRUAL key counts do not mean equal identities: two reference keys
are missing and two additional keys are emitted. Fourteen aggregate amounts are
exact, thirteen keys have exact economic line totals, and five have exact strict
line/document-amount representation. Zero journal/master-validation errors,
zero control-account/amount errors, zero matched-key sign reversals, zero date
errors, zero structural errors and zero solver/evaluator boundary violations were
found. Strict differences remain visible rather than being discarded by scorer
tolerance. All generated postings are dated 2026-07-31; no new day-one reversal.

## What matches and what does not

**WIP** is exactly 28,990,273 EUR cents for the pending works certification. The
original PDF gives cumulative 358,709,298 minus previous 329,719,025, with chapters
5,736,175 + 5,214,296 + 12,724,867 + 5,314,935. Customer, 43090000/71300000 and chapter
PEPs are retained. The original page was visually checked as well as parsed.

**BAD_DEBT** is exactly 526,350 EUR cents for company 1200/customer C200076 after
simulated collections. Synthetic tests cover thresholds, insolvency guarantees,
public/group exclusions, provision releases and missing due dates.

**PREPAID** has all nine identities, both signs and the required 480 comparison.
Five items differ by 1–2 cents from the reference's allocation rounding; the
largest absolute difference is 2 cents. These differences are reported, not
called exact because they pass aggregate tolerance. The monthly half-up/final
residual convention was fixed before evaluation.

**FX** exactly reproduces the amounts of all eight reference positions, including
EUR loan/interests in MXN and the USD bank. Six additional historical USD supplier
credit notes remain open in original/projected records: API005452 (-3,242),
API005455 (-3,787), API005487 (-5,174), API005504 (-6,225), API005513 (-4,478) and
API005529 (-2,788), all in EUR local cents. Together they add 256.94 EUR of FX loss
and reduce the corresponding debit positions by 256.94 EUR (two-sided account
L1 difference 513.88 EUR). They were not removed to force eight rows. Their real
open/settled status and reference treatment require review; this report does not
assert the reference is wrong. Revaluation deliberately has foreign currency
with amount_doc=0, not a change to document principal. Reference serialization
uses local-only representation, so strict currency differences are expected.

**ACCRUAL** remains the main limitation. Historical-rate and discrete-service
coverage estimates do not meet all reference cases. Missing aggregate keys are
1000/V100125 (reference 3,944,593 EUR cents) and 1200/V100147 (109,691 EUR cents).
Additional keys are 1000/V100129 (340,054 EUR cents) and 1300/V100173 (707,833 EUR
cents). Other keys also have quantified amount and cost-object differences in
`detail.json`. No estimator was tuned after reading these targets. Supplier IDs
above belong only to evaluation documentation, not solver rules. The report
retains each observed sample, uncovered interval, cost object, source evidence,
method and historical min/max scenario. Missing discrete consumption is not a
statistical confidence interval and is not silently declared covered.

## Balance impact

Original ERP account balances exactly match the recorded reference. Pre-M6
simulated account balances exactly match the reference pre-close projection,
computed only in evaluation as truth minus reference close entries. This does not
prove every upstream line/assignment is identical; it is an account-level result.

All final account-balance differences below arise from M6 relative to its close
reference. These are **two-sided sums of absolute account differences**, not
one-sided losses, revenue effects or cash flow. Do not sum EUR and MXN.

| Company | Currency | Original L1 difference | Upstream/pre-M6 L1 difference | Final/M6 L1 difference | Different accounts |
|---|---|---:|---:|---:|---:|
| 1000 | EUR | 0.00 | 0.00 | 76,005.86 | 7 |
| 1100 | EUR | 0.00 | 0.00 | 6,991.20 | 6 |
| 1200 | EUR | 0.00 | 0.00 | 25,413.60 | 7 |
| 1300 | EUR | 0.00 | 0.00 | 14,746.60 | 6 |
| 1910 | EUR | 0.00 | 0.00 | 87.70 | 3 |
| 2100 | EUR | 0.00 | 0.00 | 610.60 | 2 |
| 3100 | MXN | 0.00 | 0.00 | 7,971.58 | 2 |

`balance_differences.json` retains each account's original, pre-M6, M6 movement,
final and reference balances. `balance_impact.json` separately reports actual
upstream simulated adjustments and actual M6 movements, not just differences.

## Tests and environment

- Exact published source, M6 subset: **59 tests passed**, Python 3.13.5.
- Clean GitHub CI run **37127732110**, commit **1e85d58**: **555 discovered,
  506 passed, 49 skipped**, Python **3.12.14**. No failures. Install and compilation
  succeeded. The skipped organizer/live-provider cases are not claimed passed.
- Prior CI 37125690571: 385 tests, one AP evaluator-import failure, 45 skips.
  Upstream #192 fixed it; no second AP fix was implemented here.
- After merging backend 3325a4a, CI 37126021018 passed 407 tests with 46 skips.
- Earlier local full-suite run: 466 tests, two optional-import expectation failures
  and 40 skips; pydantic was already loaded by this execution environment before
  the solver. Clean CI is reported separately; those local failures are preserved.
- The initial CI doctor invocation `python -m kalmora.cli doctor` only imported
  that module. It is not claimed as a runtime check. The workflow is corrected to
  `python -m kalmora doctor`; that actual command passed locally on Python 3.13.5.
- Published-source fixture rebuild is byte-identical; published-source replay from
  an ERP/tasks-only phase passes for all ten accounting payloads, with zero
  forbidden solver accesses, zero document calls and zero LLM calls.
- `phase_test` was not supplied. A blind attempt failed on absent tasks/close;
  no hidden target, acceptance count or blind result was invented.

See the final CI artifact and delivery execution manifest for checks on any later
documentation/workflow-only commit. M6 and #171 remain open regardless of CI success.
# Current real-flow execution

The figures below preserve the historical simulated baseline. Current real
deterministic results, including September, are in
[REAL_FLOW_REVIEW.md](REAL_FLOW_REVIEW.md) and
[evidence/real-flow-20261003.json](evidence/real-flow-20261003.json).
