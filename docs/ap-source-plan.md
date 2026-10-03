# AP source-context audit (#140)

`plan_ap_sources` produces a reviewable JSON audit for every task in the verified
prepared-source inventory. It connects saved source interpretation to active ERP
identity, PO candidates, historical receipt certainty and structural invoice
requests. It does not produce AP rows, accounting decisions or journal entries.

```python
plan = await plan_ap_sources(phase_path, manifest_path)
```

The optional `receipt_as_of` argument accepts an observed `Fact` with source
evidence. A date string alone is rejected. The default is `None`; month end,
message reception and invoice date are never substituted for a missing cutoff.
No expected company or financial primary-source choice is supplied implicitly.

The connected CLI saves the returned object outside the original phase and
Golden:

```text
kalmora plan-ap PHASE --sources MANIFEST --output PLAN
```

## Meaning of the output

- `summary.task_count`, `attachment_count` and `statuses` cover the exact task
  inventory, including empty, failed, unclassified and unsupported tasks.
- `READY_CONTEXT` means source/identity/PO structure is resolved. Fiscal
  applicability, duplicate and notice inventories, monetary source bindings,
  advance/credit opening state and posting are still pending.
- `UNKNOWN` preserves missing, invalid or contradictory facts and source-role
  diagnostics. A usable structural request can coexist with this status.
- `UNSUPPORTED` identifies credit/advance documents that require other adapters.
- `run.accounting_run=False`, `run.exportsAP=False`, fiscal/monetary statuses and
  advance/credit opening statuses make the audit's scope explicit.
- `request_available` does not imply posting readiness. Request summaries expose
  `header_available=False` and `posting_available=False`.

Each task keeps original message metadata, every attachment, parser/classifier
versions, source/artifact hashes, capture provenance, raw and normalized facts,
normalization/extraction diagnostics, financial header consensus, exact identity
and scope, evidence quotations and per-line query/match/candidates. Quantities
retain milli units, unit prices retain their scales, money retains integer cents,
and exact Decimal views use the existing typed-value codec. No monetary amount
is filled from a different attachment or a master default.

The source mode remains `fixture`, `deterministic`, `record` or `replay` as
verified. Synthetic captures stay labelled synthetic; planning does not promote
fixtures to recordings. The planner's zero calls/cost describe this audit only,
not the earlier preparation of recordings.

## Batch verification and replay

Prepared-source configuration versions, exact tasks, originals and artifacts are
verified before and after the batch. The active ERP baseline, PO bridge and
identity catalogue are built once. A private invoice-context batch reuses their
read snapshot, checks all baseline hashes plus the companies master, and refuses
publication if a master changes while tasks are processed. It retains real
historical receipt consumption; the temporary receipt-only transaction state
does not assert empty historical advance or credit balances.

`source_manifest` contains the current configuration SHA and stable source
fingerprint; the raw manifest-file SHA is preserved under `execution` because
its preparation report may contain changing calls/cost. `active_erp.sources` and `source_sha256` identify the current ERP
snapshot. `stable_plan_sha256` fingerprints the complete audit excluding itself
and `execution`; elapsed time, paths and planner calls/cost belong to execution
metadata. Identical verified inputs therefore reproduce the same stable audit
and fingerprint without network, captures, extraction or semantic resolution.

The function returns a dictionary and writes no files. The CLI handles the safe
output destination. Input mismatches or concurrent changes fail explicitly;
valid source-stage failures remain per-task UNKNOWN instead of disappearing.

## Targeted verification

`tests/test_ap_source_plan.py` uses six synthetic November 2031 tasks with new
IDs: a ready ordinary context, deterministic XML, a failed residual, an empty
task, a credit note and a task with several financial sources. Tests cover exact
inventory/metadata preservation, absent cutoff, unchanged originals, single
catalogue construction, stable replay with network/extraction/capture adapters
disabled, and rejection of stale masters, originals, artifacts, configuration
and Golden manifest paths.

This source audit does not establish completion of M1 accounting acceptance,
the original July close or a September execution.
