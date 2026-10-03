# AP acceptance evidence

`kalmora.ap_acceptance` audits an existing RunBundle (`deliverables/ap.jsonl`,
optional `manifest.json`/`run.json` and `trace/`) against one active phase. It
does not create AP decisions, copy historical postings into a delivery or call a
provider. Missing rows remain missing. The July and September task counts come
from each phase's `tasks/ap_documents.json`, never from a constant.

`audit_ap_delivery` snapshots AP tasks/clock, all active ERP files and every
canonical task's original attachments. It checks saved `APSourceRun` artifacts
through the public strict `load_prepared_ap_sources` loader against those original
bytes, their manifest and installed source configuration. The loader rederives
normalization/classification and validates grounding and capture provenance.
Fixture preparation remains explicitly synthetic and blocks real delivery acceptance.
It records hashes of source bytes, facts/configuration, installed Python rules
(excluding the evaluator), policy, delivery format, output and optional bundle
trace. Rechecking the inventory and hashes after validation rejects a concurrent
change instead of producing a mixed acceptance report. It reads no golden.

Rows use the existing `validate_ap_row` with the active tax catalogue and complete
company/account/partner/CC/WBS masters, including company ownership and the close
posting window. Coded PO positions must exist in the same company/vendor/currency
scope. The audit reports exact missing, extra and duplicate keys, invalid rows,
account/partner/CC/WBS/PO dimensions, document cents and local debit/credit totals
per company/currency. A non-posting row cannot contain a journal. Duplicate trace
events/publications and POST events for non-posting tasks block acceptance.

`SOURCE_ONLY`, `PARTIAL_DELIVERY` and `COMPLETE_DELIVERY` describe coverage;
`BLOCKED`/`READY_FOR_EVALUATION` describe the checks. Complete coverage alone is
insufficient: missing/incompatible saved facts, unresolved source understanding,
invalid rows or absent/mismatched transaction replay remain blockers. A compatible
source snapshot is not evidence that a document was fully understood.
`facts.source_unknowns` preserves every declared unknown with its task, original
attachment, saved artifact, field, status and reason. The auditor validates the
strict `field`/`status`/`reason` schema: malformed diagnostics remain raw evidence
with `valid=false`, incompatible facts and a separate schema blocker. Valid
`MISSING`, `AMBIGUOUS` and `CONTRADICTORY` declarations block source completeness
even when facts, classification, rows and transaction replay are otherwise valid.
This is a conservative gate: the auditor has no upstream evidence that a declared
missing field is irrelevant to accounting. It neither converts absence to zero
nor infers resolution from an observed value. It does not invent missing-field
diagnostics for undeclared optional fields; field relevance and any evidenced
resolution belong to #140. These checks
do not assert semantic policy accuracy or a score; the evaluator is the separate
boundary for the July reference comparison.

## Provider-free transaction replay

The integration owner supplies actual, resolved `APTransactionRequest` objects,
the evidenced historical `APTransactionState`, and the active engine catalogues,
rates and master context. No arbitrary callback or provider is accepted:

```python
from kalmora.ap_acceptance import audit_ap_delivery, replay_ap_transactions

proof = replay_ap_transactions(
    resolved_requests, initial_state,
    tax_catalog=tax_catalog, withholding_catalog=withholding_catalog,
    rates=rates, context=master_context,
)
report = audit_ap_delivery(
    phase_path=phase, bundle_path=bundle,
    policy_path=participant / "POLITICAS_CONTABLES.md",
    source_manifest_path=source_run.manifest_path, replay=proof,
)
```

Replay executes `commit_ap_transaction` twice from the identical unpublished
baseline, compares the complete receipt/advance/publication snapshots and rows,
checks that non-posting requests retain the same state, and retries each committed
request to confirm it rejects another publication. It preserves request and
baseline hashes and the count of rejected retries. Recomputing from a baseline
does not append to the original ERP or consume it again. The proof's immutable
JSON bytes must match the posting rows in the bundle; the immutable non-posting
projection `(doc_id, document_type, decision)` must match its non-posting rows.
`APTransactionRequest` does not publish non-posting reasons or headers: those
fields receive contract validation, but their factual decision replay still
requires #140's upstream decision result. This is an in-process integration proof, not a
deserializer for arbitrary claimed replay statistics in a JSON manifest.

The replay helper consumes resolved typed inputs; converting saved document facts
into those inputs belongs to #140. It cannot reconstruct missing decisions from
an export or a metrics-only run manifest. Its real-engine synthetic regressions
prove the mechanics, and are never labelled July/September accounting acceptance.

## Read-only delivery tool

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/validate_ap_delivery.py \
  --phase /original/participant/phase_dev \
  --bundle /work/july-run \
  --policy /original/participant/POLITICAS_CONTABLES.md \
  --sources /work/july-sources/phase-sources.json \
  --report /work/audit/july-first.json
```

The CLI audits existing artifacts. It never initiates extraction or claims an
absent transaction replay. Reports are published atomically outside originals,
saved sources and the RunBundle, without overwriting an existing report. Exit
`1` preserves a useful `BLOCKED` report; exit `2` means the audit/publication could
not be completed. Exit `0` requires ready evidence and any requested compatibility
comparison to pass. Present CLI runs without an in-process replay are expected
to remain blocked; use the API above for the accounting integration.

`--against /work/audit/july-first.json` compares a second audit's input/rules/
policy/format/facts/output/replay identities. `--independent-phase` instead
requires the same frozen rules/policy/format and source configuration (including
residual model/prompt identity), with different input and saved-fact bytes. September
must supply its own ERP, tasks, originals and compatible saved facts; the flag
never substitutes July captures. Freeze installed code, parser/normalization,
model/prompt configuration and policy before the actual September accounting run.
The report self-hash detects corruption, not a cryptographic signature or a claim
that an upstream provider produced true observations.

The optional original-source regression uses `KALMORA_AP_PHASE` and
`KALMORA_AP_SOURCES`. It audits an actual prepared source manifest and explicitly
expects zero delivered rows and missing accounting replay. It never invokes a
model, reads evaluation data or synthesizes a row to fill task coverage.

Focused check:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover \
  -s tests -p 'test_ap_acceptance.py' -v
```

## Real integrated producer evidence (3 October 2026)

The integrated `kalmora solve-ap` v0 producer now supplies real monthly outputs.
This supersedes the earlier source-only observation of no delivery. It reads
active tasks, inbox and ERP; its `proto.run(..., gold=by_id)` argument contains
its own decisions, not reference rows. The reviewed producer path has no
per-document ID exceptions or provider call. This is the v0 parser/decision/coding
pipeline, not the typed M1 `APTransactionRequest` integration. Its source views
are not the saved v2 source facts supplied separately to the acceptance auditor.

Evidence is preserved under
[`integrated-producer`](../outputs/m1-owned-validation/integrated-producer/).
The [summary](../outputs/m1-owned-validation/integrated-producer/summary-current.json)
and [comparisons](../outputs/m1-owned-validation/integrated-producer/comparisons-current.json)
retain all counts, raw extra-field observations and evidence hashes. Each
`{july,september}-final-{first,repeat}/bundle/deliverables/ap.jsonl` is the
unchanged producer output; its `bundle/producer-proof.json` records all original
input hashes and the frozen rules. Four corresponding reports in `audits/`
retain every row diagnostic and its actual row number/ID. Earlier reports without
`final` are preserved intermediate snapshots and are not the current acceptance.

| Evidence | July | September |
| --- | ---: | ---: |
| Exact AP task keys / delivered rows | 305 / 305 | 297 / 297 |
| Posting rows / journals | 243 / 243 | 233 / 233 |
| Non-posting rows carrying a journal | 0 | 0 |
| Producer-reported coding errors | 0 | 0 |
| Accepted v2 source attachments | 58 | 48 |
| Unknown/unclassified v2 attachments | 262 | 265 |
| Invalid rows in the accounting auditor | 305 | 297 |
| Byte-identical repeated output | yes | yes |
| Provider calls / attempted Golden or network reads | 0 | 0 |
| Acceptance | COMPLETE_DELIVERY / BLOCKED | COMPLETE_DELIVERY / BLOCKED |

Both final producer repetitions and audits use rules SHA-256
`8b61a44f4f4e98875aec9c1c0e9a828bbfb56aab0b1b6d812190b59da7bbcd3c`
and source configuration SHA-256
`7b2077e56eea6008e2a3077f46c7c6af4ce2a28be08c09a4e9f4b857a6ef1896`.
The AP output hashes are:

- July: `1556f096277bcfeffc0e1aaa549115ac9533c57208a9a7c58eb85edae5b83b14`.
- September: `da043cd4fe1097c91174ab19957e67e5b115e13ca879b22492d3e593eb5df9cd`.

The guarded reproduction script [run_guarded.py](../outputs/m1-owned-validation/integrated-producer/run_guarded.py)
executes the unchanged public CLI with an explicit local `--run-dir`. It denies
Golden/network access and writes outside its own output root, and rechecks all
active ERP, AP inbox and task bytes plus code after execution. All four successful
runs have unchanged inputs and no denied-access attempts. An initial attempt
caught the CLI's default run-report destination outside that root; the successful
runs explicitly relocate those metrics, without changing production code.
September uses the independently preserved original ZIP phase, without July
state/captures. The independent-phase comparison passes frozen rules, policy,
format and configuration identity, while input/fact hashes differ. The comparison
still reports `acceptance_status=BLOCKED`.

### Exact current auditor findings

The delivery example permits `action:null` on POST. Our accounting validator
omits only that null optional value from a checker copy, preserves raw output,
and still requires the exact action for NOT_INVOICE. The shared M0/evaluator
Literal checker continues to report null actions as invalid; its report is
preserved independently. This correction exposes later accounting checks instead
of changing any producer field.

The following are **diagnostic occurrences**, not distinct failing-row counts.
A row can have several failures. `ap.jsonl:1` is the singleton row checker's
message prefix; the enclosing audit item retains the actual line and document ID.

| Exact error text | July | September |
| --- | ---: | ---: |
| `ap.jsonl:1.currency: expected str` | 15 | 19 |
| `ap.jsonl:1.invoice_date: expected str` | 3 | 5 |
| `ap.jsonl:1.net: expected int` | 15 | 19 |
| `ap.jsonl:1.gross: expected int` | 15 | 19 |
| `ap.jsonl:1.tax: expected int` | 62 | 64 |
| `ap.jsonl:1.withholding: expected int` | 62 | 64 |
| `ap.jsonl:1.retention: expected int` | 62 | 64 |
| `ap.jsonl:1.payable: expected int` | 62 | 64 |
| `unexpected AP fields` | 243 | 233 |
| `unexpected coded-line fields` | 1430 | 1267 |
| `foreign journal components require document cents` | 11 | 11 |
| `GR/IR needs unambiguous coded cost correspondence` | 7 | 102 |
| `journal document amount differs from coded cost dimension` | 7 | 13 |
| `coded line requires expense/asset or advance-request account` | 0 | 1 |
| `journal document base does not conserve coded net and capitalized VAT` | 5 | 5 |
| `advance request document amount differs from header` | 1 | 1 |
| `supplier side/document payable differs from header` | 6 | 6 |
| `charged VAT does not match deductible/import or capitalized treatment` | 0 | 1 |
| `AP journal partner differs from header vendor` | 1 | 1 |
| `lines[1].partner: required for open-item account` | 1 | 1 |
| `this decision does not carry a rejection/HOLD reason` | 0 | 3 |

| Category | July occurrences | September occurrences |
| --- | ---: | ---: |
| Null/type shape failures | 296 | 318 |
| Extra delivery fields | 1673 | 1500 |
| Foreign currency/document-cent evidence | 11 | 11 |
| Accounting dimensions | 14 | 116 |
| Document amount conservation | 12 | 12 |
| VAT treatment | 0 | 1 |
| Partner | 2 | 2 |
| Decision/reason compatibility | 0 | 3 |
| Debit/credit balance or non-integer journal sides | 0 | 0 |

Raw field inventory separately finds `action_data` on all 305/297 rows and
`goods_receipts` on all 1430/1267 coded lines; those fields are outside the current
`ApRow`/`ApLine` contract. Non-posting null/type failures return before extra-field
checks, explaining why the auditor's `unexpected AP fields` count is lower.
No fields were dropped or nulls converted to zero. Independent `validate_entry`
checks of all 243/233 raw journals with active masters find one missing open-item
partner in each phase, and no debit/credit-balance errors. This narrower check does
not prove invoice currency conservation, fiscal treatment or original imputation.
The accounting auditor accepts no row, so its accepted dimensions/totals are
empty; that must not be read as an absence of accounting activity.

### Separate July reference comparison

[July's full comparison](../outputs/m1-owned-validation/integrated-producer/july-final-evaluation.json)
uses only `kalmora.evaluation`'s loader, `compare_ap`, diagnostics and the unchanged
original scorer. September has no reference comparison. The AP-only official
score on raw bytes is **0.99147757364168** (99.1478%): 302 exact and 3 partial
entities. The report retains all differences, 589 shared-checker structural
errors, 5 company mismatches, one `ENTRY_RULE` and one `REFERENCE_ENTRY_RULE`.
The latter two both identify `API004469`'s missing open-item partner; a reference
defect does not excuse the submitted defect. Differences remain for
`API004130`'s coding/journal cost object, `API005230`'s DUPLICATE versus HOLD and
`API005227`'s POST versus REJECT. These IDs are evaluator findings, never solver
exceptions or tuning instructions.

Scorer SHA-256 is
`b8adec99c609098c7781b4d34cd08ddd6c7d62830800ac9b37d5b1213ca0828e`.
The expected Downloads package manifest is absent; `manifest_verified=null` is
preserved. The low-level AP comparer gives the permissive scorer's metric while
also preserving invalid structure; the public all-module `evaluate` entrypoint
would refuse this structure. A high AP score is therefore neither schema
acceptance, full accounting validation nor transaction-state replay.

### Remaining owners and reproduction

The exact blockers for both months remain `AP_OUTPUT_INVALID`,
`SOURCE_UNDERSTANDING_INCOMPLETE` and `TRANSACTION_REPLAY_ABSENT`:

- The producer/integration owner (#140) must map its observations to the #55
  delivery contract, keeping internal metadata in evidence and preserving true
  unknowns. The auditor must not repair or fabricate missing monetary values.
- Currency, cost correspondence, VAT, payable and partner findings require the
  producer to consume the existing evidenced monetary/journal contracts (#51–54)
  through #140. Decision/reason findings require its policy-result integration;
  weakening the validator or changing the reference is not a resolution.
- Saved-fact completeness requires original-grounded extraction (#39–41),
  compatible residual captures tracked in #222, and #140's field/decision
  integration. V0 parser success is not recorded evidence
  that the separate v2 unknown attachments were resolved.
- Transaction replay requires actual resolved `APTransactionRequest` objects
  and evidenced opening state through #140, then the replay API above. Re-running
  a stateless producer from originals proves byte repeatability, not atomic
  publication, cumulative receipt/advance consumption or duplicate-event refusal.

From the Developer repository, the successful evidence can be reproduced with
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python` and the preserved scripts. For example:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  outputs/m1-owned-validation/integrated-producer/run_guarded.py \
  --phase /Users/juanjosefernandezmorales/Downloads/participant/phase_dev \
  --output outputs/m1-owned-validation/integrated-producer/july-final-first/bundle/deliverables/ap.jsonl
```

Repeat in the corresponding `*-repeat` bundle; use the preserved independent
`original-september/participant/phase_test` for both September runs. Audit each
raw bundle using `tools/validate_ap_delivery.py`, its own phase's v2
`sources-first/phase-sources.json`, and the original policy. The preserved
[evaluate_july.py](../outputs/m1-owned-validation/integrated-producer/evaluate_july.py)
and [summarize_current.py](../outputs/m1-owned-validation/integrated-producer/summarize_current.py)
reproduce the AP-only comparison and current summary without repairing a row.
Audit reports use exclusive creation: rerun to a new report destination, preserving
this frozen snapshot. No complete test suite was rerun for this evidence work.

## Independent criteria and the explicit v0 contract view

`audit_ap_delivery(..., project_v0=True,
 documentary_acceptance_reference="User instruction accepting the documentary base provisionally")`
opts into the `ap-v0-contract-v1` view. The default audits the raw contract. The
reference must identify actual user authorization; a caller-supplied string is
recorded evidence, not a signature or proof of document understanding.

The view removes only the v0 root `action_data`, coded-line `goods_receipts`, and
null values of optional header fields on known non-posting decisions. Every
omission has a line number, document ID, JSON pointer, reason and original value
in `projection.changes`. `output_sha256` and `projection.original_sha256` still
identify the untouched delivery bytes; `projection.projected_sha256` identifies
the validation view. Malformed JSON and unknown fields remain failures. Required
posting values, reasons (including `DUPLICATE`), money, payees, decisions, coding,
journals and contradictory non-null facts are never filled or changed. A raw
artifact requiring projection retains `RAW_OUTPUT_REQUIRES_CONTRACT_PROJECTION`;
the auditor never rewrites it as an accepted export.

Reports now contain one `documents` record for each exact task ID and a
`criteria_summary` with independent statuses. Duplicate rows are ambiguous and
missing rows are absent; neither selects an arbitrary output row. Criteria are:

- `documentary`: public source-loader compatibility, attachment classification,
  packet diagnostics and declared field unknowns. Provisional documentary
  acceptance preserves `INCOMPLETE`, `MISSING`, `AMBIGUOUS` and `CONTRADICTORY`.
- `contract`: TypedDict shape and permitted fields, with the documented
  `action:null` exception; domain invariants are reported separately.
- `strict_row_validation`: the complete existing accounting/decision validator,
  with all diagnostics retained.
- `master_scope`: observed company/vendor/currency, PO/item and coded dimension
  ownership against the active phase, even when shape or documentary checks fail.
- `journal_validation`: the independent ledger validator for posted rows, checking
  integer local cents, debit/credit, balance, dates, partner and cost objects.
- `nonposting_journal`: no journal field on non-posting rows, including null.
- `document_currency_conservation`: strict document/local correspondence. Absent
  optional `amount_doc` on foreign document components is `INCONCLUSIVE`, not a
  shape contradiction or an inferred conversion. Explicit local-currency FX
  lines do not require foreign document cents. Observed currency contradictions
  remain failures; the full strict diagnostics also remain visible.
- `transaction_replay`: actual typed transaction proof, or `ABSENT`. Posted rows
  must match in full; non-posting replay covers identity/type/decision only.

`accounting_summary.validated` counts only rows clearing contract, the complete
strict validator and active-master scope. It is independent of documentary
accuracy and replay. `monthly_acceptance` is always false: readiness for later
evaluation, structural checks and partial non-posting replay do not prove monthly
policy accuracy. `delivery_ready_for_evaluation` names the narrower readiness
condition. Existing overall blockers remain explicit. A high score, byte repeat,
provisional documentary acceptance or a count of valid rows cannot turn absent
transaction replay into a proof.

The CLI exposes `--project-v0` and `--documentary-acceptance-reference`; it prints
criterion counts and preserves exit status 1 for blocked evidence. Repeated and
independent-phase comparisons additionally freeze the projection version and
documentary acceptance reference, along with existing rule/policy/format and
source configuration checks. July facts are never transported into September.

Focused verification uses `tests/test_ap_acceptance_projection.py` (actual
transaction factories on explicit synthetic fixtures, not monthly results).
It covers raw-byte/metadata retention, unknown sources, absent replay, invalid
posting money, scope and partner/balance failures hidden by an invalid header,
non-posting journals, duplicate tasks, malformed JSON/rows, optional foreign
cents, legitimate local FX components, and explicit CLI scope. Real producer
runs and their audits remain separate evidence; this test suite does not invent
rows for missing tasks or claim a monthly delivery.
