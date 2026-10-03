# Document evaluation contract (#139)

Release status, 2026-10-03: the user accepts Luna provisionally and defers the
remaining quality gate to [hotfix #222](https://github.com/alfonsomayoral/talky-labs-hackathon/issues/222).
See [measured results and acceptance decision](evaluation/luna-provisional-release.md).
The evaluator continues reporting actual failures; production integration can
proceed under this explicit provisional approval.

This evaluator consumes explicit original-source annotations and captures. Solver code must never import `kalmora.documents.evaluation` or access these fixtures. No model has been evaluated by this commit. Closing #139 requires the parent's frozen live benchmark; unit tests and source audits establish harness behavior only.

The frozen sample remains 20 documents: 12 tuning and eight holdout. Holdout labels were manually sealed before live evaluation, after reviewing eight original PDF pages (including the image-only page) and two XML documents. The label file byte SHA-256 is `e471a50c39383d96681a891f7fb142696dfb60fb3d41408165720de266f0c866`. It contains 191 facts plus eight document types, 189 critical slots, 64 visible line amount/quantity slots, and eight manually resolvable semantic checks. No intrinsic ambiguous real semantic case exists in this partition; the abstention denominator is zero, rather than a fabricated success. Synthetic ambiguous and incorrect-candidate guards are tested separately. Repeated organizer templates overlap between partitions; these results cannot establish generalization to unseen layouts.

Annotations keep original attachment paths/hashes, dates normalized to ISO by explicit DMY/MDY convention, exact money strings in major units, and per-attachment values. Original ERP anchors support semantic candidate identity. No golden files, phase_test, model responses, or generated accounting solutions were used. The two-page attachment's invoice summary and supplementary measured table have separate `lines` and `detail_lines` namespaces. Counts and explicitly absent fields are manually reviewed structural evidence; they are not invented OCR substrings. Image quotes are manual visual transcriptions, and their grounding requires the sealed page and matching transcription/value. Unreviewed image extras fail the fabrication gate. Raw synthetic identifiers remain intact.

## Explicit evaluator API

```python
from kalmora.documents.evaluation import evaluate_sample
report = evaluate_sample(
    manifest, annotations, captures,
    source_root=participant_root,
    semantic_results=semantic_results, candidate_sets=candidate_sets,
    run_reports=run_reports, scope="tuning", output_path=report_path,
)
assert report["passed"]
```

`manifest` and `annotations` accept dictionaries or JSON paths. `captures` maps sample case aliases to M0 `DocumentFacts`, serialized attachment lists, or an envelope with `raw_facts` and `normalized_facts` lists of M0-shaped attachment records. An optional `unified_values` mapping must retain `None` for explicitly annotated conflicts. Canonical aliases include `document_number`/`invoice_number`, `recipient_tax_id`/`buyer_tax_id`, `document_type_hint`/`document_type`, `line.N.field`/`lines[N].field`, and `certification_current`/`certified_current`. Lexical document classification recognizes explicit source titles; semantic production classification remains the classifier's responsibility. Numeric/date normalization uses deterministic syntax and explicit units/order, never case IDs or expected answers. Floats are rejected for exact money. Additional normalized contracts should adapt explicitly to this boundary.

Semantic results use `check_id` with case alias fallback and provide `selected_ids` plus status. `candidate_sets` maps the same keys to the IDs actually supplied to the selector. Selected IDs outside that set fail even when otherwise plausible. Original master rows are hashed and checked against sealed labels. Required-field exactness, prediction precision, evidence grounding, completeness, source-supported extras, unresolved observations and preserved conflicts are reported with explicit denominators. Per-field/per-format and per-case tables expose small-N results. Unknown ground truth never becomes a false label; text extras can be proved source-supported without asserting semantic correctness.

## Frozen gates and live accounting

For a manually reviewed absent slot only, an explicit source-bound `MISSING`
unknown with a nonempty reason can satisfy exactness and field completeness.
The capture envelope records `unknown_states` with field, status, reason,
document and original source hash. Omission alone, another document/hash, an
ambiguous/contradictory state, or an unknown for a present label cannot pass.
This records a correct absence abstention without creating `Fact(None)` or
claiming a grounded observation. Returned-observation grounding and prediction
precision denominators are unchanged; reports expose absence abstentions
separately. This protocol interpretation is fixed before holdout evaluation and
does not modify labels, partitions or acceptance thresholds.

Quality gates remain fixed: critical exactness and critical prediction precision at least 95%; returned observation evidence grounding 100%; fabricated values/IDs zero; semantic selection precision 100%; unique resolvable coverage at least 80%; ambiguous abstention 100% where applicable; required-field completeness at least 95% per case; estimated capture cost at most USD 0.10 per document. Unknown cost fails. The user removed temporal limits on 2026-10-03: request deadlines and the former p95 <=60s acceptance gate are disabled. Actual durations and p95 remain reported. The named contract revision records this explicit change before holdout; arbitrary threshold changes still fail. The aggregate experimental budget is USD3, at most two attempts per operation and concurrency two. The user also removed the application output-token cap; the API omits it and spending reservations use verified physical model capacity. The runner enforces spending, attempts, concurrency and the no-retuning holdout policy. Multiple independent attachments or semantic operations are not retries of one request.

Runtime reports are actual `RunRecorder` JSON per case, including completed calls with provider `openai`, candidate model `gpt-6-luna`, nonzero known usage, and explicit USD/per-token prices and provenance. The evaluator reproduces estimated cost using Decimal. Reports require `input_metadata.capture_mode="captured_live"`, `transport_mode="default"`, and `response_source="provider_api"`. Synthetic/test-fixture markers exclude live confirmation. Cached-only zero-cost runs and replay/model mocks cannot establish live quality. These runner attestations are a trust boundary: an evaluator cannot independently prove that a caller honestly used the default transport. Persist actual production RunRecorder reports and client configuration with the benchmark.

`capture_correctness_passed` reports offline correctness separately. `passed` requires correctness plus live provenance, performance, and cost. Missing runtime reports fail the live gate. This commit does not contain scores, latency estimates asserted as observations, or fabricated provider bills. Any later full-AP run needs an explicit estimated budget before execution.

The user approved raising the aggregate experimental spend cap to USD 5 on
2026-10-03 for a GPT-6.1 Sol comparison without limiting model output. This
changes only that cap, retaining all quality, latency, retry and per-document
cost gates and the original sealed holdout. Necessary further experimental
extensions are authorized; each run still declares and audits its budget.
Reservations for unknown usage are
not reported as zero charges or silently released.

## Independent image quotation review

Unlabelled image observations and quotes extending beyond a sealed transcription
remain unreviewed. The evaluator accepts an optional `image_reviews` mapping, or
`--image-reviews` typed-v1 registry file. Reviews bind the exact field, typed value,
unit and complete quote to the original source, page, actual image and captured
transformation hashes. Only an explicit `VERIFIED` original-page-image review
can establish quote fidelity; `REJECTED`, missing or stale records fail acceptance.
Source/image identity and literal value support are checked independently first.
OCR text or confidence cannot verify an observation. Review records remain solely
in the evaluator and never enter capture prompts, solver inputs or expected field
answers. The report includes the review-registry fingerprint. The records attest
the reviewer's inspection; they cannot cryptographically prove honest inspection.

## Validation

Run the focused unittest module with `PYTHONPATH=src`. Set `KALMORA_PARTICIPANT_ROOT` to the original participant root to additionally verify the sealed label hash, partition size and original source/quote anchors. PDF source auditing requires the existing documents runtime's `pypdf`; no OCR or commercial judge is invoked. Tests use clearly synthetic fixtures for wrong numbers, missing fields, fake evidence, hash tampering, invented IDs, ambiguous abstention, threshold mutation and cache/mock runtime rejection.
