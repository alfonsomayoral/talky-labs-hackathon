# M5 implementation review — 2026-10-03

PR [#196](https://github.com/alfonsomayoral/talky-labs-hackathon/pull/196)
targets `backend`. This review reproduces the producer's delivery and fixes a
projection defect. It does not constitute a GitHub approval or milestone closure.

## Reviewed source and correction

The producer head was `99feeba337b1da218e3f9d62e55b1368cfa7aa9d`.
Upstream backend `7e8064876a90b66783e5d30c1adaffb54f5f0203` was merged without
conflicts. Solver checks below use correction commit
`5a25b20` and Python 3.12.2 in a separate checkout.

**P1 — Already projected external corrections were posted again.** Duplicate
reversal and wrong-partner rules observed the immutable ERP, then deduplicated
only by M5's own event/stage. An AP-owned reversal or bank-owned reclassification
with a different owner was ignored. The reproduced wrong-partner example changed
a reconciled pair back to a 333-cent discrepancy while reporting `complete=true`.

M5 now consumes a complete external correction only when company, reference and
the full financial lines match, including taxes, assignment, document currency
and cost objects. It preserves the external owner and retains the original
incident with no new journal. One external journal covers one incident; partial
corrections, excess reversals and simultaneous own/external correction produce
`EXISTING_IC_CORRECTION_CONFLICT`. A different invoice's reversal is not consumed.
Restored corrections are recognized even when the new producer delivery omits
an already projected entry.

Eight regression cases cover these boundaries. Four of the initial five cases
failed before the correction; the final eight pass alongside the existing suite.

## Executed validation

- Full backend unit suite: **621 discovered, 542 passed, 79 skipped**. API/dev
  dependencies and Pydantic were installed; optional document/LLM/landing and
  other external-data checks were not all enabled. This is not an all-features run.
- M5 suite with `KALMORA_IC_PHASE` pointing to the original solver-only July data:
  **108 passed, no skips**, including recorded ERP preservation and replay.
- `compileall`, `kalmora doctor` and `git diff --check`: passed.
- Actual organizer package SHA-256:
  `c813449eab9ddc7fc28b04eff85518957035e895b5500fd19e26c0d8ef7f0109`.
- AP/bank fixture contracts rebuilt from that package: 305 AP documents,
  6 IC-relevant AP journal entries, 56 bank corrections. The 236 other posted AP
  entries are explicitly outside this projection scope. This does not validate
  the full AP delivery.
- An isolated solver process denied reference, evaluator and ZIP access. Its
  guard probe passed; the solver attempted no forbidden reads. Two fresh runs
  produced identical IC bytes. Replay emitted no new IC corrections, preserved
  the original ERP and left the corrected ledger unchanged. The missing pooling
  sweep remained a single bank-owned entry linked to `BL0005652`.

Before evaluation, 153 tracked Python source/tool files and the submission were
hash-frozen. The hashes of the executed IC files also match the freeze. The
unchanged original scorer and the actual shared `compare_ic` were run separately;
their results agree.

IC SHA-256:
`599cd3f5759b16113b8808690a135b3447c710ecfc270b189eee30913f98b71b`.

Recorded ledger SHA-256:
`110da2bb3408b29e38d8addb7ed1ace9418db6f23b972fa53c520a78e98bfd50`.

Corrected ledger SHA-256:
`ec1bbd0cbc7550c00955452926b0eb2a7084296dc9be3884c4b0dc0f1e01292b`.

## Acceptance still fails on three additional findings

The frozen output contains eight rows. **All fields of all five reference rows
match**, including the reference's additional line dimensions. The official IC
score is **0.8615**; the three extra transit rows prevent exact acceptance.
The projection defect correction does not alter this package's IC bytes.

| Invoice | Issuer → receiver | Net expense, EUR cents | Emitter journal |
| --- | --- | ---: | --- |
| IC1000-26-0034 | 1000 → 2100 | 3411200 | 1000-2026-1800000034 |
| IC1000-26-0035 | 1000 → 3100 | 4316000 | 1000-2026-1800000035 |
| IC1100-26-0007 | 1100 → 1910 | 5693200 | 1100-2026-1800000007 |

Each is issued on July 31 and remains an emitter-side open item. Independent
joins, including normalized reference numbers, found no receiver journal,
AP invoice register, historical AP document log, supplied receipt or IC-relevant
AP entry matching these references. The declared task pairs include all three.
Policy §6 calls for accrual of issued but unreceived invoices and contains no
exception for these cases. On the available evidence, they cannot be removed
solely to reproduce the reference's five-row count. This remains a source/policy/
reference discrepancy requiring resolution under #94.

## Reproduction and remaining gates

Use the commands in [m5-intragroup.md](m5-intragroup.md), fresh input/output
directories and the unchanged organizer ZIP. Enable the data test with:

```bash
KALMORA_IC_PHASE=/path/solver-inputs/participant/phase_dev \
  python -m unittest discover -s tests -p 'test_ic*.py' -v
```

Then freeze source/submission hashes and use `m5_evaluate.py --freeze ...
--require-shared`. The review checkout retains unit logs, the failing regression
log, input and fixture manifests, isolation/replay reports, the hash freeze,
normalized source joins and original/shared evaluation artifacts under its
untracked `review-evidence/` directory. Source ERP and reference data are not
added to this public PR.

M5 and its epics remain open. #94 retains the reference disagreement; #159 still
requires actual AP #55 and bank #73/#75 outputs through the same contracts,
ownership checks and full evaluation. All reviewed dependency runs here are
**simulated**. Neither a passing modular run nor matching five reference rows
proves the real AP → banks → IC flow. The PR remains a draft pending acceptance.
