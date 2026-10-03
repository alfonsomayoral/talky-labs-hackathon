# Comparator (#35): design record

Working record for issue #35 (M0-09, "Integrar el scorer original y el comparador"). Status: **implemented on branch `35-comparator`**; see "Implementation and evidence" at the end. Questions are written before they are researched; decisions are appended under each question.

Goal (from the issue): per-module metric and per-entity detail; golden reachable only by evaluation, never by the solver; reproducible evidence (partial evaluation, difference detail, solver/evaluator separation, coverage, discrepancies, run measurement).

Known facts (observed, not decided):

- `participant/score.py` (311 lines) returns aggregate numbers per module plus a weighted total. It is the organizer's scorer and must stay unmodified.
- `participant/` is git-ignored and this checkout has no `phase_dev/golden/`. The real July golden was inspected from `~/Downloads/participant/phase_dev/golden` (same `score.py`, SHA-256 `b8adec99…828e`); see "Observed golden facts".
- `PhaseData` rejects any path containing `golden`; there is no evaluator-side reader yet.
- `docs/discrepancies.md` already lists three comparator obligations: scorer field gaps, company omitted by `je_match`, and the API004469 / 407 `partner=null` exception.

## Observed golden facts (July, `phase_dev/golden`)

Read-only profile of the real files; none of this is inferred.

- **Volumes:** ap 305, ar_billing 26, ar_cash 32, bank_rec 12 accounts, ic 5, close 76 rows (64 scoring keys), trial_balance_truth 259 rows, trial_balance_recorded 244 rows. `summary.json` agrees with the counts.
- **AP:** decisions POST 242, HOLD 19, REJECT 18, DUPLICATE 14, NOT_INVOICE 12; `POST_PAYMENT_BLOCK` is absent. Every POST has a `journal_entry`; none of the other decisions do. `doc_id` is unique.
- **Close types:** ACCRUAL 57, PREPAID 9, FX_REVAL 8, WIP_REVENUE 1, BAD_DEBT 1. There is **no** `DOUBTFUL_RECLASS` in July. The 76 rows collapse to 64 scoring keys; the multi-row keys seen are ACCRUAL by (company, vendor).
- **Golden carries fields the delivery format does not list:** AP `cases`, `due_date`, `credit_note_of`, `action_data`; close `je`, `period`, `estimate`; ar_cash `account`, `date`, `amount`, `kind`; bank_rec `gl_account`, `statement_opening/closing`; ic `account`, `detail`, `note`. They are not scored.
- **Company on lines:** AP, ar_billing and close entries carry `company` only at entry level (0 of 2,357 lines have it); ar_cash, bank_rec and ic adjustments carry it on every line.
- **Partner null on a partner-prefix account:** 33 lines on `55500000` (32 ar_cash `TRANSFER`, 1 bank_rec `UNRECORDED_RECEIPT`) are the convention that matches the format examples, plus **one** anomaly, API004469 `40700000`. The scorer requires the partner to equal the golden's on prefixes 40/41/43/44/49/55/24/16, so a submission that adds a partner to a `55500000` line loses credit.
- **Cross-references resolve:** all 302 golden `book_line` ids exist in the journal and all 286 golden `bank_line` ids exist in the bank files. Golden entries post in `2026-07`.
- **Ceiling and floor (run outside the repo):** golden copied as a submission scores **100.0** in every module including the trial balance. An empty submission scores **3.54**; `ar_cash` alone gives 0.2359 because several golden receipts have empty applications/residuals.

## Questions

### Q1. Wrap the original scorer or reimplement it?

*Why it matters:* a reimplementation can drift from the official number; a wrapper is bound to `score.py`'s internal API.
*Owner:* @danielorlando97. *Acceptance:* the headline module scores and total equal `python score.py` exactly; `score.py` is never edited.

### Q2. How is per-entity detail obtained when `score.py` only returns aggregates?

*Why it matters:* the issue requires detail per entity, and the scoring functions expose none.
*Acceptance:* every entity gets a score and typed differences; module means derived from entity results reproduce the original module scores, or the exceptions are named.

### Q3. Where does the comparator live and how is golden access kept away from the solver?

*Why it matters:* acceptance criterion 2 and the issue's "evidence of solver/evaluator separation".
*Acceptance:* a single evaluator-side reader of golden; solver modules cannot import it; a reproducible check demonstrates this.

### Q4. How does the comparator surface the gaps the scorer does not catch?

*Why it matters:* `docs/discrepancies.md` requires field, chronology, attribution and item validation beyond the score, explicit company validation, and the API004469 exception.
*Acceptance:* each gap appears as a labelled diagnostic that does not alter the official score.

### Q5. What is the unit of detail for modules whose scoring key is not one row (close, ic, bank_rec, AP decision F1)?

*Why it matters:* close aggregates rows into scoring keys (76 rows / 64 keys in July); AP's decision metric is a dataset-level macro F1; IC and close are dataset-level F1.
*Acceptance:* each module has a documented entity unit and a stated rule for extra (non-golden) submission rows.

### Q6. What is the report format and where is it written?

*Acceptance:* machine-readable report plus a readable summary; includes provenance (golden hash, scorer hash, submission hash, run id); written outside the solver's reach.

### Q7. How is a partial evaluation reported?

*Why it matters:* the scorer gives 0 to missing modules and the issue requires a partial-evaluation demo.
*Acceptance:* missing modules are explicit; no invented normalized total.

### Q8. How are the comparator and its evidence validated, given golden is not in the repository?

*Why it matters:* CI cannot read golden; `AGENTS.md` forbids adding or running tests without an explicit request.
*Acceptance:* a reproducible evidence procedure that does not require committing golden.

### Q9. What does the comparator do with `phase_test` (no golden)?

*Acceptance:* a clear refusal for scoring and, at most, structural validation of the submission.

### Q10. How does this relate to the deprecated #32?

*Acceptance:* no new output-contract module; structure diagnostics only.

## Decisions

Research basis: the repository, `score.py` and a feasibility probe run on synthetic rows outside the repo. No external web source was material: the decisions depend on the organizer's scorer, not on an industry standard. Alternatives were weighed against the acceptance criteria of each question.

### D1 (Q1). Wrap `score.py`; never reimplement the headline

Alternatives: (a) port the formulas into `kalmora` (drifts silently if the organizer ships a corrected scorer for `phase_test`); (b) run `score.py` as a subprocess (hard to attach entity detail); (c) import it as a module. **Chosen: (c).** Load `participant/score.py` from the registered package with `importlib`, check its SHA-256 against `manifest.json`, and take module scores and total from the original functions. The comparator's headline is `score.py`'s own result dict, unchanged.

### D2 (Q2). Per-entity detail by calling the original functions on one-entity slices

`score_ar_billing([g], [s])`, `score_ar_cash`, `score_bank` and the per-document parts of `score_ap` are plain averages, so a slice returns that entity's exact score. Probe: mean of slices equals the whole-set score. For *why* a score is below 1, a line-level explainer reuses the scorer's own `je_lines`, `norm_line` and greedy matching, so the lines that fail to match are named. Reconciliation rule: for averaged modules the mean of entity scores must equal the original module score; the comparator reports a mismatch as an error. Set-based modules (AP decision F1, IC, close) are explained by status, not by slicing (see D5).

### D3 (Q3). Separate evaluator package; only it reads golden

A new `kalmora.evaluation` package owns the golden reader, the comparator and a `kalmora evaluate` command that takes the evaluator phase directory explicitly (no discovery). `PhaseData` keeps rejecting `golden`. Solver modules must not import `kalmora.evaluation`. Evidence: a static import-boundary check plus the run report recording which inputs were read.

### D4 (Q4). Gaps surface as labelled diagnostics that never change the official score

- **Company:** probe shows a journal entry on the wrong company still scores 1.0 in `je_match`. Compare the entry-level company (AP, ar_billing, close) and the line-level company (ar_cash, bank_rec, ic) against the golden, since golden carries them at different levels.
- **API004469 / 1100-2026-5100000822:** probe shows a correct line with the creditor partner scores 0.5 against golden `partner=null`. Annotated as a `known_exception` linked to `discrepancies.json`, shown explicitly, never hidden or compensated.
- **Partner convention on `55500000`:** 33 golden lines carry no partner and the scorer requires that. Reported as a `scorer_convention` note, not as an exception, so a legitimate partner on a 555 line is explained and not blamed on the solver silently.
- **Entries:** unbalanced or malformed submitted entries (via `validate_entry`), non-integer amounts, bad dates, missing keys that the scorer silently defaults.
- **Items:** missing and extra entities per module.
- **Chronology and attribution:** the discrepancy register names them without defining them. Interpreted here as (chronology) posting dates outside the close month (golden posts all in `2026-07`) and (attribution) entity ids that do not exist in the phase inputs (`doc_id`, `bank_line`, `book_line` all resolve for the golden, so this check is feasible). This interpretation is an assumption to confirm.

### D5 (Q5). Entity unit per module

| Module | Entity | Notes |
|---|---|---|
| ap | `doc_id` | decision hit/miss, plus per-part scores; F1 stays dataset-level |
| ar_billing | `billing_item` | |
| ar_cash | `bank_line` | |
| bank_rec | `account` | with line-level detail for matches, unmatched and adjustments |
| ic | (sorted pair, cause) | hit / miss / extra |
| close | scoring key from `close_key` | lists its contributing rows (76 rows, 64 keys in July); hit / partial (0.4) / miss / extra |
| trial_balance | (company, account) | delta against truth and against recorded |

Submission rows with no golden counterpart are listed as `extra`. They change the score only where the scorer itself counts them (precision in IC, close, and bank unmatched sets).

### D6 (Q6). Report format

`outputs/evaluations/<uuid>.json` (git-ignored, created through the existing `RunRecorder` convention) plus a terminal summary. Sections: `headline` (exact `score.py` dict), `modules[].entities[]` with typed differences `{field, expected, actual, kind}`, `diagnostics`, `provenance` (package, golden, scorer and submission hashes). `schema_version: 1`.

### D7 (Q7). Partial evaluation uses the scorer's semantics

A missing file scores whatever `score.py` computes for an empty list, which is **not always 0**: an empty submission gets `ar_cash` 0.2359 and a total of 3.54 on July. The report shows the scorer's number, marks `file_present: false`, and adds `answered/total` per module so a floor score is not mistaken for work done. No normalized or "coverage-adjusted" total is invented.

### D8 (Q8). Evidence without committing golden

A documented procedure run against the participant package, in the style of the existing optional integration check: (a) golden copied as a submission, the ceiling (already observed: 100.0 in every module); (b) empty submission, the floor (observed: 3.54); (c) partial submission; (d) single mutations (wrong company, partner added on a `55500000` line, amount off by 3 cents). Synthetic fixtures and unit tests are added only if the user asks, per `AGENTS.md`.

### D9 (Q9). `phase_test`

No golden: `kalmora evaluate` refuses to score and exits non-zero with a clear message. `--structure-only` may run the D4 submission diagnostics alone.

### D10 (Q10). Relation to #32

No contracts module. Structure checks are diagnostics inside the comparator.

## Open risks and blockers

- **Golden is outside the repository.** It lives in `~/Downloads/participant`; the comparator takes the evaluator directory as an explicit argument and must work from a registered package (`data/<dest>/participant`) produced by `import-package`. The July shapes are now observed; `phase_test` will have none.
- **Scorer drift.** The organizer might ship a corrected `score.py` for `phase_test`. Mitigated by hashing and loading the scorer from the registered package.
- **Chronology / attribution** interpretation in D4 is an assumption.
- **Slicing fidelity.** Set-based modules cannot be sliced; their entity statuses are derived and checked against the original F1.

## Implementation and evidence

Code: `src/kalmora/evaluation/` (`scorer`, `compare`, `explain`, `diagnostics`, `boundary`, `report`, `exceptions`) and `kalmora evaluate`; row types in `src/kalmora/output_models/`. Differences from the plan:

- D4 also reports **unscored fields** per entity (`unscored`): AP `document_type`/`currency`/`action` and journal presence, AR invoice `date`/`currency`/`deductions`, cash residual `invoice`, bank adjustment `category` and `company`, IC `amount`/`responsible`, close row count and journal presence. Balance dimensions beyond company/account are **not** compared.
- Entity detail uses one-entity slices of the original functions where the module is an average (ar_billing, ar_cash, bank_rec, AP parts); AP decision F1, IC, close and the trial balance repeat the scorer's rule and are reconciled against the original number.

Evidence (July, `phase_dev`, registered with `import-package`; run `kalmora evaluate ... --evaluator <phase> --text`):

| Run | Result |
|---|---|
| golden copied as submission | 100.0, every module exact, reconciliation ok, 0 unscored differences |
| empty submission | 3.54 (`ar_cash` 0.2359), reconciliation ok |
| only `ap.jsonl` | 36.38, other modules marked `file missing` |
| POST changed to HOLD | AP 0.9975, total 99.92 |
| 3 cents added to one AP entry | AP 0.9997; diff names the line (2226956 vs 2226959); `ENTRY_RULE` unbalanced |
| partner added to a `55500000` line | `ar_cash` 0.9969; `SCORER_PARTNER_CONVENTION` |
| wrong entry company | score 100.0 unchanged; `COMPANY_MISMATCH` |
| IC row removed, bank category changed | IC 0.8533, bank_rec 0.9989, total 99.24 |
| unknown `doc_id` appended | score unchanged; `UNKNOWN_ENTITY` |
| scorer altered after registration | rejected: hash differs from `manifest.json` |
| no golden | refuses to score, exit 1 |

`mypy --strict` passes on `evaluation/` and `output_models/`; `mypy` passes on the whole package. The run used a re-zipped copy of `~/Downloads/participant` (archive hash differs from the organizer's ZIP; `score.py` hash `b8adec99…828e` is identical). No unit tests were added; `AGENTS.md` forbids that without a request.

Not covered: `phase_test` (no golden available), and balance dimensions beyond company/account.
