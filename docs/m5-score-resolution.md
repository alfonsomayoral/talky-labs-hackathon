# M5 score resolution and modular integration

The user authorized integrating PR #196 after resolving the three additional
transit findings and trying to maximize the score. Investigation found no source
rule that supports dropping those invoices. PR #196 was squash-merged into
`backend` as `4856b1810fbb517e82e822afe7ee07d9087b5ea9`. Implementation tasks
#88–#94 and epics #18/#19 are complete. Reference acceptance and actual producer
integration remain tracked separately under #239 and #159.

## Remaining score penalty is structural

All five reference keys are detected and every expected journal scores 1.0.
All required output fields and additional reference line dimensions also match.
The original scorer weights cause detection at 60% and journal matching at 40%.
Keeping the three additional source-supported keys gives:

```text
true positives = 5; false positives against the reference = 3; missing = 0
detection F1 = 2 × 5 / (2 × 5 + 3) = 10/13
IC score = 0.6 × 10/13 + 0.4 × 1 = 56/65 = 0.861538…
official rounded score = 0.8615
```

Thus 0.8615 is the maximum IC score for an output retaining these eight keys
against this unchanged reference. Changing signs, amounts or journal lines
cannot improve it because the expected journal component is already perfect.
Reaching 1.0 requires either omitting the three supported keys or resolving the
source/reference inconsistency. No reference key list, fixed row count, company
exception or learned invoice ID was added to the solver.

## Source and cross-module checks

The three invoices remain issued and open on July 31:

| Invoice | Issuer → receiver | Gross EUR cents | Net expense EUR cents |
| --- | --- | ---: | ---: |
| IC1000-26-0034 | 1000 → 2100 | 3411200 | 3411200 |
| IC1000-26-0035 | 1000 → 3100 | 4316000 | 4316000 |
| IC1100-26-0007 | 1100 → 1910 | 6888772 | 5693200 |

Normalized joins found no matching receiver posting/accrual, AP invoice register,
historical AP log, receipt contract, or current structured inbox document. All
three pairs are declared by the phase tasks. Policy §6 requires receiver accrual
for issued but unreceived invoices and specifies no grace period or cross-border
exception. Their allocation is independently supported by receiver history.

A separate **evaluation-only** inspection of `golden/close.jsonl` also found no
matching accruals for these references or IC counterparties. They are not already
assigned to M6 by the reference. The inspection did not feed close or IC reference
data to the solver. The authoritative package and reference files were unchanged.

## Final pre-merge verification

Upstream backend `62c248faf3739a9e4bbc1d7fd09615c507ca87da` was merged without
conflicts; M5 source files were not changed to fit the reference.

- Backend suite with the original July IC data enabled: **682 discovered,
  597 passed, 85 skipped**. The other optional feature/data checks were not all
  enabled. The M5 corpus check is included in the passing tests.
- Fresh isolated AP/bank fixture runs and replay: all checks passed; source ERP
  and corrected projection hashes were preserved. The IC bytes remain
  `599cd3f5759b16113b8808690a135b3447c710ecfc270b189eee30913f98b71b`.
- **157** Python source/tool files and the submission were frozen before a new
  original/shared evaluation: 5/5 expected rows exact, official IC **0.8615**,
  unchanged source since freeze.
- Compile and whitespace checks passed. The PR's Python 3.12/3.13 CI must pass
  on the final published head before squash integration.

An attempted September corpus check could not run: this organizer ZIP contains
only `phase_dev`, with no `phase_test/tasks/close`. Its failure log is retained
as an unavailable-input attempt, not represented as a passing blind-phase check.

Evidence is retained in the separate review checkout's untracked
`review-evidence/`: normalized source joins, cross-module ownership inspection,
the exact score ceiling proof, pre-merge unit/isolation logs, freeze and original/
shared evaluation reports. See [implementation review](m5-independent-review.md)
for the corrected external-ownership defect and prior evidence.

## Acceptance after integration

The original scope of #94 requires comparison, scoring and separate validation
of required fields; it does not require a score of 1.0. Both epics explicitly
allow July differences to be resolved or documented. The earlier statement that
#94 must remain open until the reference disagreement is resolved added a
condition by interpretation. The comparison is complete and the discrepancy is
preserved in [#239](https://github.com/alfonsomayoral/talky-labs-hackathon/issues/239).
Tasks #88–#94 and epics #18/#19 were closed with their checklists and evidence.

Verification on merged backend `4856b18`: **703 tests discovered, 607 passed,
96 skipped**, with the original July IC corpus enabled. The earlier independent
M5 run passed all **108 tests without skips**. Python 3.12/3.13 CI passed on the
final PR head `326f087` before integration. These are recorded runs on those
commits, not a claim that every optional backend feature was exercised.

An additional partial integration used the real bank producer: 12 accounts,
59 adjustments and no unresolved bank cases. IC recognized the bank-owned
pooling correction for `BL0005652` / `CP2607221200`, retained the original
27,053,177-cent finding and emitted `adjustment: []`. AP remained a fixture, so
this mixed run has `real_flow_verified=false` and does not satisfy #159.

M5 remains open. #239 requires substantiated source/rule clarification or a
corrected organizer reference, followed by a new frozen comparison. #159 requires
complete real AP receipt/export and bank deliveries through the same interfaces,
evaluation and replay without dependency fixtures. The disclosed IC score remains
0.8615 until the reference discrepancy is resolved.
