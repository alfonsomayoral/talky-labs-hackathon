# Source-driven field recovery (#222)

July's v17 comparison exposed missing headers and whole-document rejection from
one invalid field. The new opt-in `--staged` capture flow changes the unit of
work and validation rather than selecting successful reruns.

1. XML remains a deterministic literal source adapter. Recognized complete
   native invoice tables retain deterministic rows and separately recorded
   outside-table interpretation.
2. Image documents and incomplete native tables receive separate recorded
   `header_footer_only` and `tables_only` operations. Other native documents
   retain a complete operation with explicit header state coverage. The source
   plan is determined before model outputs, without case IDs or labels.
3. Every requested header field requires a literal observation or a reasoned
   unknown. The generic checklist covers title, number/date, parties and tax
   identifiers, currency/totals, PO, IBAN and periods. It never establishes that
   a value exists. Omissions trigger validation feedback against the original.
4. Invalid attempts retain independently grounded candidates and field-level
   issues as `PARTIAL`, including proof/source/prompt identities. They cannot
   load through the successful facts API. Repair feedback supplies errors and
   coverage gaps, without rejected answer values. Only the final strictly
   validated response is accepted; attempts are never merged to pick winners.
5. Each stage has its own recording key. A successful header survives a failed
   table for diagnosis/retry, while no final combined artifact is emitted.
   Offline evaluation reloads the accepted recordings, verifies header states
   and scopes, and recomputes combined facts. Raw provider responses remain
   separate from combined source facts.

Prompt v18 is shorter and scope-specific. Default v17 instructions and request
identities remain unchanged. `required_header_fields`, scopes, repair limits
and partial-preservation mode participate in the new recording identity.

This follows [OpenAI's structured output guidance](https://developers.openai.com/api/docs/guides/structured-outputs)
for explicit schemas and [document-understanding guidance](https://developers.openai.com/cookbook/examples/multimodal/document_and_multimodal_understanding_tips)
for faithful source transcription and focused original-image inspection. Schema
adherence does not establish factual correctness. Original source tools remain
open source; Luna remains the provisionally approved provider model.

## Acceptance boundaries

`capture_valid` means both operations passed their recording/grounding boundary.
`source_table_coverage` remains `unverified` for model tables: returned row IDs
alone cannot prove all printed rows were read. Native coverage and independent
original-image/source review remain required. Unknowns never become observed
nulls or accounting approval; `accounting_eligibility` is `not_evaluated`.

Supplier identity is now an explicit bounded operation derived from observed
tax IDs and the original vendor master. It can run without a recipient company;
PO/receipt queries still require exact vendor/company constraints. No supplier
IDs, expected answers or organizer golden enter extraction inputs.

Normalizer/XML v3 corrections follow the [source contract alignment](document-contract-alignment.md).
Old XML adapters require their frozen code revision for replay: changed mappings
cannot silently reinterpret historical captures. Old reports stay immutable.

## Development comparison fixed before execution

Only the same twelve July tuning cases are recaptured, once each, in a fresh
output directory. Previously evaluated holdout cases are not rerun or used to
declare blind improvement. Before calls, freeze source/module/configuration
fingerprints, v18, Luna low, validation two/transport one, concurrency two,
original 300 DPI renders/strips, no OCR in prompts, and unchanged quality gates.
No timeout/output-token cap; declared experimental budget USD 5; conservative
input/output rates USD 0.25/0.75 per million, estimates rather than bills.

The prior v17 and archived v10 reports provide the comparison. This is a
development measurement across changed pipelines, not a controlled prompt-only
experiment or a new reserved acceptance pass. Report omissions, failures,
unreviewed image quotes, semantic operations and all actual costs. Fresh blind
acceptance still needs a new fixed protocol and disjoint reserved originals.
