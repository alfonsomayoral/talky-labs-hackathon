# M6 close — simulated development delivery

**Status: implementation delivered for review; NOT accepted as real-flow integration.**
Existing upstream PR: #197 (draft), target `backend`, head
`juan-fernandez-gotherlabs:codex/m6-close`. The same code is published directly in
`alfonsomayoral/talky-labs-hackathon:codex/m6-close`. Implementation tracking
#20–#23 and #95–#104 is closed; M6, #171 and #251 remain open.
No main or M5 work-branch writes are part of this delivery.

Read `METHOD.md`, `CONTRACT.md`, `RESULTS.md`, `ISSUES.md`, `REVIEW.md` and the current
incremental `SCORE_INVESTIGATION.md` together. RESULTS.md preserves the original
78.507% baseline; the source corrections now yield 79.0977% in simulated close.
`PR_BODY.md` is the maintained description for the existing PR. Current source
reviews are in `reviews/` and machine evidence in `evidence/score-investigation.json`.
Source CI passes in both repositories: 66 M6 passes and 839 backend passes /
40 skips on Python 3.12.14. The real-flow gate remains open.

## Reproduce

Use Python >=3.12 and an unmodified participant directory containing `phase_dev`
and `score.py`. Outputs must be outside the phase. The July participant ZIP has
no `phase_test`. September originals are available in the primary checkout under
`data/septiembre/participant/phase_test`; no blind-phase result is claimed.

```bash
python -m pip install -c requirements-m1.lock -e '.[documents,llm,landing,api,dev]'
export PYTHONPATH=src
python -m kalmora doctor
python -m unittest discover -s tests -p 'test_m6_*.py' -v
python -m unittest discover -s tests -v

PHASE=/absolute/path/to/participant/phase_dev
OUT=/absolute/path/to/new-m6-run
mkdir -p "$OUT"
# Authorized upstream-only fixture adapter. Its access guard denies close targets.
python tools/m6_fixture.py --phase "$PHASE" --output "$OUT/dependencies.json"
# This command has no golden or document-extractor dependency.
python -m kalmora.close --phase "$PHASE" --handoff "$OUT/dependencies.json" \
  --output "$OUT/frozen"
# Fresh process, guarded I/O/imports/network, saved facts only.
python tools/m6_replay.py --phase "$PHASE" --handoff "$OUT/dependencies.json" \
  --expected "$OUT/frozen" --output "$OUT/replay"
# Only now may the evaluator read close and trial-balance references.
python tools/m6_evaluate.py --phase "$PHASE" --output "$OUT/frozen" \
  --report-dir "$OUT/evaluation"
```

The replay was also executed against a separate physical `phase_dev` directory
containing only `erp/` and `tasks/`: no golden, inbox or bank directory existed
there. All ten accounting payloads were byte-identical. The eleventh file,
`freeze.json`, contains execution timestamps and is not claimed byte-identical.
Earlier progress text referring to eleven identical accounting files included
that manifest imprecisely; the machine replay report is authoritative.

The close command exits 2 on invalid inputs and 3 when enumerated engine inputs
are incomplete. `engine_data_complete` is not an assertion that every real-world
service has been observed. Coverage limitations and estimation sensitivity remain
separate, and the manifest always leaves real-flow acceptance to #171.

## Outputs and retained evidence

`close.jsonl`, `close_decisions.jsonl`, `projection_events.jsonl`, three account
balances, three dimensional position snapshots, `balance_impact.json`, and a
sealed execution manifest. Evaluator reports include strict line dimensions,
document amounts, signs, dates, aggregate keys, account-level balance differences
and accrual sensitivity. The delivery ZIP includes the sealed dependency file,
those outputs, reports, original-source observation evidence, commands, test/CI
logs, source hashes and an applicable patch. Original ERP/inbox/tasks/golden are
not edited or supplied as a replacement dataset.

## Transfer text through gh (existing PR only)

```bash
gh pr view 197 --repo alfonsomayoral/talky-labs-hackathon \
  --json number,isDraft,baseRefName,headRefName,headRefOid
gh pr edit 197 --repo alfonsomayoral/talky-labs-hackathon \
  --body-file docs/m6/PR_BODY.md
gh pr comment 197 --repo alfonsomayoral/talky-labs-hackathon \
  --body-file docs/m6/REVIEW.md
gh pr checks 197 --repo alfonsomayoral/talky-labs-hackathon
```

These commands neither mark the PR ready nor merge it. Independent review,
remaining accounting acceptance and real M1–M5 evidence are still required.
The original connector was fork-write-only. The native gh session now has upstream
push access; both repositories receive the same branch commits. PR #197 keeps its
original fork head for continuity and its description is updated through gh.
