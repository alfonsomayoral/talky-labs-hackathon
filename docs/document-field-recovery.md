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

## Measured July development result

The frozen v18 run completed 11/12 cases and 12/13 original attachments. The
same tuning annotations and acceptance gates remain in place. Full numerators,
denominators, configuration/module identities and limitations are published in
[the result summary](evaluation/july-field-recovery-results.json). Prior results
in [the July comparison](evaluation/july-hybrid-comparison.md) remain unchanged.

| Measure | Original v10 | Previous v17 | Source-driven v18 |
| --- | ---: | ---: | ---: |
| Captured cases | 9/12 | 8/12 | 11/12 |
| Critical fields exact | 68/94 (72.34%) | 39/94 (41.49%) | 74/94 (78.72%) |
| Required fields exact | 78/114 (68.42%) | 45/114 (39.47%) | 83/114 (72.81%) |
| Grounded observations | 481/546 (88.10%) | 599/647 (92.58%) | 877/925 (94.81%) |
| Critical prediction precision | 66/68 (97.06%) | 39/40 (97.50%) | 73/75 (97.33%) |
| Acceptance | Failed | Failed | Failed |

Critical exactness improves by 37.23 percentage points over v17 and 6.38 over
v10. This combines source planning, coverage checks, prompt changes and adapter
corrections; it does not isolate the effect of any one change. Observation
denominators also change with the values returned by each pipeline.

Known estimated cost is USD 0.06355025, including rejected attempts, with zero
unknown reservations. Recorded p95 is 50.48 seconds versus 33.11 for v17; this
version improves recovery, but has not demonstrated a speed improvement.
Latency has no acceptance limit by user instruction. Semantic coverage rises
from 0/4 to 2/4, with 2/2 selections correct, and still misses the 80% gate.
All twelve accepted attachments reproduce offline with zero provider calls and
network access forbidden. The failed PDF is explicitly excluded from successful
replay, while remaining in quality and cost denominators.

An independent reviewer checked T12 against the original PDF, its 300 DPI parent
render and three pixel-identical crops, without labels/golden. All 26 printed
priced rows were checked. Its 231 unique verified identities cover 148 raw and
147 normalized observation instances; none were rejected or left unreviewed.
T12 nevertheless scores 12/14 required fields because two delivery references
are omitted. An ambiguous period date remains raw rather than guessed.

## Remaining acceptance work

- T03 retains an accepted XML attachment but rejects its PDF after both recorded
  validation attempts. The first returned observed fields as `MISSING`; the
  second used unsupported header fields. Proof-checked partial candidates remain
  diagnostic, and are not credited as a successful capture.
- The evaluator reports 48 unsupported observation instances: 41 from XML
  captures and seven involving date literals or derived row counts. Source
  contracts need explicit proof-preserving adapters for those meanings; changing
  assertions or silently treating a count as a printed literal is not a fix.
- Notices/certificates still omit some effective dates, beneficiaries, validity,
  balances and panel/presence facts. These require source-grounded, document-type
  contracts beyond the generic header checklist. PO/delivery references and
  cross-attachment conflict preservation also remain incomplete.
- Critical exactness is below 95%, grounding below 100%, and zero fabrication
  has not been established. Only one case meets the per-case completeness gate.
  The completed cases carry live provenance, but the failed case prevents a
  whole-sample live-capture acceptance claim.

Issue #222 stays open. None of these development results establishes September
accuracy, a fresh reserved pass, or the official accounting score. The frozen
capture modules stayed byte-identical through evaluation and backend integration;
subsequent work must be measured as a separate candidate.
