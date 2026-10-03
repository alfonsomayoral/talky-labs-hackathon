# Grounded document interpretation (#137)

`LLMDocumentExtractor(client).extract(document)` returns M0 `DocumentFacts`.
`extract_with_response(document)` returns
`ExtractionArtifact(facts, raw_response, request_metadata, unknowns, provenance)`.
`LLMSemanticResolver(client, max_selections=1, max_candidates=100).resolve(request)`
returns `ResolutionResult`; `resolve_with_response(request)` returns
`ResolutionArtifact(result, raw_response, request_metadata, provenance)`.
Both artifacts have JSON-ready `to_dict()` methods for atomic recording of the
validated result and sanitized original response together. The stage recorder
owns persistence; these adapters do not read recordings, masters, golden or files.

The client is #135's asynchronous typed Responses adapter. Images become
`ImageInput(data=original_image_bytes, media_type=original_mime)` in source order.
Pydantic output models are built lazily; importing the module does not initialize
an API provider or import Pydantic. No real model calls were made while
implementing this module; original-source model quality is evaluated separately.

## Facts and uncertainty

Strict DTOs reject additional properties and floats. Observations contain a
logical field, raw scalar value, `OBSERVED`/`EXPLICIT_ABSENCE`, block ID, quote and
optional image page/hash. Amounts, quantities, prices, rates and dates remain
literal strings. Integer cents, milli quantities, VAT calculations, account
choices, duplicate/receipt checks and final decisions belong to deterministic
normalization and accounting engines. `document_type_hint` is the literal title
(for example `FACTURA`), not an arbitrary normalized `INVOICE`; #40 may apply a
documented lexical map later.

Canonical fields cover supplier/recipient identities, document references,
currency and amounts, PO/receipt/contract references, service periods,
certifications, retentions, notices and certificate dates. `line.<1-based row
index>.<field>` preserves observed quantity/UOM/price/amount/tax/description/
material/order/item/delivery details. The generic `raw.<literal_field_name>`
extension permits later AR/other-document lexical fields while rejecting
accounting-owned names. Stable allowed field lists and prompt instructions are
in `extractor.py` and `prompts.py`; they are not learned from filenames or golden.

Missing fields have no fact. Separate `unknowns` represent MISSING, AMBIGUOUS or
CONTRADICTORY, with reasons. MISSING cannot coexist with an observed field;
CONTRADICTORY requires distinct grounded observations. Multiple values remain
multiple `Fact` objects, including disagreements within a document. Separate
PDF/XML attachments retain independent source hashes and facts; this layer
does not reconcile or prefer one amount. A value of `None` is accepted only for
EXPLICIT_ABSENCE with a sourced absence statement naming the field, or a real
empty XML leaf supplied by the parser. Merely failing to extract something
never creates `Fact(None)`.

`line_count` is derived from unique contiguous line IDs, not returned by the
model. Its physical evidence locator comes from a retained line fact, and
`provenance.derived_fields.line_count` records method, line IDs and source fields.
Replay recomputes the count from accepted facts. This does not prove the model
found every original table row: annotated evaluation independently checks
completeness and original row count.

## Evidence checks and their limits

Every fact's `Evidence.document` equals `ParsedDocument.path`. Text/XML evidence
uses `ParsedBlock.source_field` where present, otherwise block ID; its page is
the source block page. Nonempty quotations must be source substrings after
whitespace normalization. Values must occur literally within their quotations;
string token boundaries prevent obvious truncated-identifier matches. A real
empty XML leaf is the only supported empty text quotation, for explicit null
absence. XML path and attribute provenance are retained unchanged.

Image evidence may select a short `image_id` from the versioned request manifest,
in the same order as supplied images. The caller obtains its actual page/hash
from the selected bytes; it never asks the model to calculate or copy a hash.
IDs are exact source-local choices, including multiple images on one page.
Unknown IDs, blocks on another page and conflicting optional page/hash values
fail closed. Legacy explicit page/hash proof remains supported without fuzzy
matching or repairs. Source and transformation hashes still bind replay to the
original bytes. Prompt/schema versions and `image_locator_version=1` distinguish
the new protocol; legacy recording parameters reproduce their original payload.

Image evidence requires an actual matching image hash/page and a source block
on that page. Its field is `image:<sha256>` and its quote is nonempty. The literal
value must occur in the transcription, but that does not verify pixels.
`provenance.image_quote_review` identifies quotes needing original-image review.
No substring/OCR verification is claimed for image-only documents.

These checks prove location and literal support, not semantic labeling or OCR
truth. Label correctness, transcription fidelity and complete extraction require
the original-source acceptance evaluation. A schema-valid response with a
fabricated block, quote/value or image hash fails closed. A grounding failure
raises `DocumentInterpretationError` with category, source path/hash and the
raw response/request metadata; no partial facts are returned. Client refusals,
incomplete output, schema and operational errors retain their `LLMError` category
and gain source/provenance metadata; they are never converted to accounting
decisions or successful empty extraction.

## Bounded semantic resolution

The caller supplies already filtered `Candidate(id, attributes)` objects and
context through `ResolutionRequest`. Optional generic guards are
`context["hard_constraints"] = {attribute: exact_expected_value}` and
`context["excluded_ids"] = [provided_candidate_id, ...]`. These are exact-value
guards, not a query language: use the PO catalog for domain filters, minimum
quantities, dates, eligibility and receipt availability. Typed canonical
fingerprints preserve Decimal/int/string distinctions during comparison.

Selection IDs must belong to that set, be unique, obey all guards and fit the
configured selection limit. Default single selection cannot infer a multi-PO
quantity allocation. Each selected ID needs proof identifying a supplied
candidate attribute/value and a grounded source value/quote/block (or image
page/hash). Proof for an unselected ID or a fabricated candidate attribute/value
fails. The resolver returns no quantities, tax policies, allocations or accounts.
AMBIGUOUS/NO_MATCH require empty IDs and no selection proof plus an explicit
reason. A citation verifies the inputs to the semantic judgment; it cannot
deterministically prove descriptions are equivalent. Review/evaluation measures
selection precision and abstention separately.

## Reproducibility and validation

Artifacts preserve prompt version/content hash, schema version/hash, original
hash, parser version and transformation hash, along with the client's actual
model/settings/request hashes and per-call metadata. Resolution additionally
preserves the full request fingerprint, including candidate attributes/context,
and selection/candidate limits. Change prompt/schema versions when their
interpretation contract changes; the stage recorder includes these identities
in its compatibility key. The adapters add no independent cache or retry loop.

Original text, XML, email and candidate context are explicitly untrusted data
in JSON payloads. Fixed instructions prohibit following embedded commands,
tools, filesystem/web/golden lookup and treating filenames as answers. Offline
injection tests exercise that boundary and output rejection; they do not claim
live-model injection resistance without original-source evaluation.

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_document_extractor.py -v
```

The optional LLM extra is required for typed tests. Tests use invented source
blocks and an injected provider through the real bounded client, recording
usage without API access. Cases cover raw headers/line fields, unknown versus
absence, XML paths/empty leaves, conflicts, large-image source hashes, fabricated
evidence/fields, strict float rejection, refusal, injected instructions,
candidate ID/attribute proofs, exact constraints, abstention and split rejection.
No golden content is used as extraction fixtures.

The extractor and resolver expose `version` before a request and
`recording_identity(provider=None)` for constructing recording configuration.
Identity includes model, fixed instructions, output schema, token/image guards
and stage parameters; budget, prices, scheduling and retry timing are operational.
A source or response never changes this version. `prompt_sha256` in request
metadata identifies the actual document-specific prompt; the identity's
`prompt_sha256` and metadata's `instruction_content_sha256` identify the fixed
instructions. Schema identity uses the contracts fingerprint; provider output
schema hashes remain separate transport metadata. Injected transports receive
an explicit `injected:<module>.<class>` identity rather than claiming OpenAI.
