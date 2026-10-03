# M2: current-phase billing from original documents

`kalmora.billing.source_runner.build_billing_from_sources` connects the five AR
support families to the existing billing engine. Its result holds `billing`
(`BillingRun`), `report`, `report_path`, `complete`, and `stable_sha256`.

```python
source = await build_billing_from_sources(data, work_dir=state, mode="record")
if source.complete:
    write_billing(source.billing, destination)
```

`complete` covers every task ID, including tasks whose `item.json` is missing or
invalid and therefore cannot become a typed `BillingItem`. Publication is separate
and requires this coverage check. The existing writer publishes both
`ar_billing.jsonl` and `pending_wip.jsonl`; pending certifications produce close
input without an invoice or a billing journal entry.

## Source and interpretation boundaries

1. Read `tasks/ar_billing_items.json` and parse each original `item.json`
   independently from its supporting documents. The declared `documents` list
   establishes expected attachment coverage; discovered additional files remain
   visible and are also processed.
2. Route originals with `DocumentRouter`. `NativeBillingExtractor`, shared
   `RecordedExtractor`, and `StageRunner` capture literal values with original
   path, quotation, page/block, bytes hash, and transformation identity.
3. Normalize explicit numeric formats with exact units, retaining every literal
   capture separately. No document observation is populated from item metadata,
   annotations, development answers, or the golden.
4. Bind printed references against the active phase's masters. Exact matches
   precede an optional bounded semantic resolver. Each attachment preserves its
   own reference proofs and diagnostics.
5. Combine only compatible independently checked observations and pass typed
   facts to `build_ar_billing` with its current-phase duplicate checks enabled.
   Complementary header evidence can be combined. Contradictions and incompatible
   complete table coverage remain unresolved; rows are never silently renumbered.
6. Preserve v0's task-order numbering convention with ERP-derived invoice series,
   then rebuild invoices and journal assignments using those explicit numbers.

Missing originals, unrecognized layouts, invalid evidence, missing captures,
reference ambiguity, and accounting rejection remain explicit unresolved work.
There is no automatic fallback to v0 or to historical task answers.

## Capture, replay, and audit

The default native reader makes no provider calls and records zero actual cost.
The shared recording API's positive cap is a technical requirement for local
callbacks, not an incurred cost. Optional semantic capture requires an explicitly
supplied response-aware adapter and positive budget; replay accepts a recording
configuration or an existing replay boundary and cannot receive provider callbacks.

`work_dir/recordings` contains checksum-verified shared captures;
`work_dir/stages/<type>` contains extraction state; `work_dir/evidence` contains
the parsed originals, literal facts, normalized observations, and reference proofs.
`ar-source-report.json` records task coverage, source diagnostics, resulting
decisions, pending WIP count, and actual new calls/cost. Report writes are atomic.

Capture identity includes original bytes, parser/transformation identity, literal
schema/prompt, reader configuration, and normalizer version. Residual resolver
requests also include the literal extraction hash and current phase context.
The stable output hash excludes operational cache-hit/mode differences. The
runner rechecks original inputs before publishing its report and rejects work
directories or artifact symlinks that would write into source data or golden.

## Validation and limits

The source runner tests use independently authored text originals to exercise
strict record/replay, changed or missing sources, metadata coverage, complementary
and conflicting attachments, pending WIP, and output path guards. They need no
reference answers or provider connection.

The July development source run resolved all 26 tasks from originals: 25 invoices
and one pending certification with WIP input. Shared native record and replay
produced the same stable output hash with zero provider calls and zero cost.
The existing writer produced both delivery files. The frozen outputs were evaluated
separately; see [July verification](../verification/m2-source-workflow.md).

The native reader covers the supported text templates. Scanned pages and new
layouts remain unresolved for separate interpretation/review. Semantic adapters
can select only eligible existing identities; they cannot decide approval, fill
missing amounts, or supply accounting values.

Functional M2 closure is authorized with July/v0 compatibility; the remaining
M1 integration belongs to #140. The existing M6 handoff independently re-parses
`documento.pdf` and requires both known pending phrases. July supports that
boundary, but this M2 runner's complementary attachments or alternative filenames
do not establish general M6 support. No M6 implementation is changed here.
