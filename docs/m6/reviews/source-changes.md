# Independent team review of M6 source corrections

Reviewed 3 October 2026, read-only except this report. Scope: `tools/m6_sources.py`, `tests/test_m6_tools.py`, `.github/workflows/m6-validation.yml`, and `docs/m6/SCORE_INVESTIGATION.md`. This is team review, not maintainer approval or real-flow acceptance for #171. No suite, solver, or evaluator was rerun by this reviewer.

## Finding identified and resolved before publication

**P1 — Reissued historical estimates must not be added as independent costs.** The initial `daily_samples()` groups and sums both posted invoice observations and historical `CLOSE_ACCRUAL` estimates for identical service intervals. The latter are not necessarily additive: the original ERP reverses and reissues the same obligation at later closes. Summing both doubles the rate sample for one obligation.

Concrete original source evidence, all in `data/julio/participant/phase_dev/erp/journal_entries.jsonl`:

- Lines 30859 and 33069: entries `1000-2026-1000000107` (30 April) and `1000-2026-1000000121` (31 May), same reference `ACCR-API003793`, provider V100030, cost center CC-1000-DIR, period 1–30 April, account 62800000, each 485791 cents. The first is reversed at line 31272 on 1 May. These are one estimate reissued, not 971582 cents of separate consumption.
- Lines 30906 and 33097: entries `1100-2026-1000000327` and `1100-2026-1000000369`, same reference `ACCR-API003695`, provider V100040, WBS OB-1100-2518.05, period 1 March–30 April, accounts 62800000 (176425 cents) and 63100000 (14114 cents). The first is reversed at line 31285.

Root repaired the helper before publication. Historical records are sorted by ISO closing date and reduced to the latest estimate for each `(reference, start, end)` within the already isolated company/provider/cost object series. Different references remain separate obligations and can contribute additive estimated costs; posted invoice grouping remains additive. This removes repeated-close double counting while preserving separately identifiable obligations. The evidence digest is only a fallback when a reference is absent; original extracted history carries explicit references.

Two additional synthetic regressions cover the repair: a reissued estimate changing from 1500 to 1800 cents retains only the latest 1800 even when input order is reversed, and two distinct references for the same interval sum 1500 + 3000 to 4500. Static re-read confirms both assertions match the repaired algorithm. The root-owned `outputs/m6-score/final-tests.log` records 66 M6 tests passing, including both new cases; this reviewer inspected that log but did not run the suite.

## Other reviewed changes

- Posted observations (`POST` and `POST_PAYMENT_BLOCK`) may contribute financial samples. Held/rejected/duplicate invoices retain receipt coverage. The revised set insertion no longer lets a rejected first arrival suppress a subsequently posted corrected document. This is consistent with the distinction between source receipt and posted financial cost. The adapter still assumes upstream decisions correctly deduplicate posted invoice business identities.
- Additive actual invoice amounts are grouped within company/provider/cost object/account and exact coverage interval; actuals replace a prior estimate for that same interval. The last-three-period median is retained. Extra source-evidence lists are sealed in the handoff and retained in the full decision components, so aggregation remains traceable. No provider-specific target constant is introduced.
- The professional guard preserves unknown current consumption when history shows discrete events. Two distinct full-month service intervals are an explicit conservative engineering assumption, not a rule required verbatim by policy §5. The report describes the assumption and does not claim the guard recovers missing target coverage.
- The workflow repository condition legitimately enables the same M6 validation job for both the fork and upstream repository; workflow scope otherwise remains unchanged.
- The score report accurately distinguishes a +0.59028167433511 percentage-point improvement in the close component from whole-challenge score, unchanged recall, an eliminated unsupported key, remaining FX/prepaid differences, and the worsening company 1000 balance difference. Values match the saved final evaluation summary at review time.
- The report correctly keeps replay of fixture-derived facts separate from real/no-golden/September acceptance. Before publication, regenerate evidence if the repair changes hashes/results and ensure the declared machine evidence and current CI results exist.

## Conclusion

One concrete historical aggregation regression was found and repaired by root. The corrected helper and two new regressions were statically re-reviewed; no remaining actionable defect was found within this review scope. The changes are consistent with original policy/source precedence and honestly document remaining acceptance limits. Final score evidence must be regenerated against the repaired source and the current upstream base before publication; this review does not approve a merge or close #171.

Publication note from the primary agent: the repaired output was subsequently
frozen and evaluated separately; it retains the same 79.09774436090226% close
score with SHA-256 `8f062c48fc8951f4462b07f67cb3d0d3dd33e4d22e0fefd1d05589c9637562e9`.
Its ERP/tasks-only replay matches all ten files. Source CI on `95cd046` passes
in upstream and fork (66 M6 tests, 839 backend passes / 40 skips). See
`../evidence/score-investigation.json` for the actual evidence and retained limits.
