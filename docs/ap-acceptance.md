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
