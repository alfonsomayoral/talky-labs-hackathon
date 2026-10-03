# Recording and document stages

`kalmora.documents.replay` and `runner` use Python 3.12 and existing M0
dataclasses only. Importing or replaying them requires neither PydanticAI,
OpenAI, Pydantic, a key, nor network access. They replace interpretation
boundaries, never accounting rules, calculations, validations or output writers.

## Modes and contracts

- `record`: an explicit provider/model configuration, positive exact USD budget
  and injected asynchronous callback are required. Bind callbacks to
  `LLMDocumentExtractor.extract_with_response` or
  `LLMSemanticResolver.resolve_with_response`. The shared `AsyncLLMClient`
  enforces reservations, retries, concurrency and unknown-cost budget holds;
  recording does not create another provider/client or relax that budget.
- `replay`: read compatible **recorded** envelopes only. Missing, corrupt,
  mismatched or unsuccessful captures raise `ReplayError`, with stage/key/category.
  Provider callbacks are rejected. There is no fallback to a live request.
- `fixture`: read explicitly **synthetic** envelopes through the same interfaces.
  Fixtures may use reviewed original-source annotations, with their basis in
  provenance; they remain identified as synthetic doubles, not measured model
  responses. Never construct fixtures from golden outputs.

`RecordedExtractor.extract(ParsedDocument)` returns `DocumentFacts`.
`RecordedResolver.resolve(ResolutionRequest)` returns `ResolutionResult`.
Both expose `*_with_response` artifact methods with accepted value,
sanitized raw response, request metadata and provenance; extraction also retains
`unknowns`. They implement the same asynchronous boundaries as the live adapters.
Negative/ambiguous resolution is an explicit typed abstention, not an accounting
decision. Refusal, malformed response, timeout and budget errors are separate
operational failure envelopes, never successful empty facts.

```python
from decimal import Decimal
from kalmora.documents.replay import RecordingConfig, RecordingStore, RecordedExtractor

# Load a reviewed configuration bundle; no model/schema runtime import needed.
config = RecordingConfig.from_dict(configuration_json)
store = RecordingStore('build/records')

# Capture: extractor's existing client owns the actual shared run cap.
capture = RecordedExtractor(store, config, mode='record',
    callback=live_extractor.extract_with_response, budget_usd=Decimal('1'))
facts = await capture.extract(parsed_document)

# Offline: no live_extractor, provider factory, key or callback is constructed.
offline = RecordedExtractor(store, config, mode='replay')
same_facts = await offline.extract(parsed_document)
```

## Cache identity and atomic envelopes

`RecordingConfig` includes provider, model, extractor version, prompt version
**and actual content hash**, schema version **and actual schema hash**, and a
caller-supplied parameters/context bundle. Include relevant selection limits,
reasoning settings and phase/state versions in that bundle. Configuration secrets
are rejected; changing configuration during an in-flight request is an error.
Capture metadata, when supplied, must agree with declared model/prompt/schema.

The key includes original source SHA-256, parser version, the complete parsed
representation/transformation hash (including text, pages, original image hashes
and source path), and configuration fingerprint. Resolution additionally uses
`ResolutionRequest.sha256`, which covers current candidates, their attributes
and relevant context. Masters or prior selection changes therefore invalidate
semantic reuse; a selection is never applied to an incompatible candidate set.

The accepted typed result and sanitized original response share one atomic JSON
envelope in `entries/<key>.json`. The complete configuration, unknowns, versions
and request metadata are retained. The `typed-v1` M0 encoder preserves exact
`Decimal` values and container shapes. A checksum covers the payload, not just
the cache key. All captures are also retained in `history/<key>/<checksum>.json`
before an atomic current-pointer update, so explicit regeneration does not erase
earlier evidence. Failure envelopes live separately in `failures/<key>.json`.

Replay verifies envelope schema/key/checksum, configuration/origin, accepted
source hash/extractor version, grounded evidence, and current candidate proofs.
Text/XML evidence uses the exact relative document path, block `source_field`
(otherwise block ID), source page and a nonempty quotation matching after
whitespace normalization. Literal values must appear in the quotation.
Two narrow exceptions are validated explicitly:

- `Fact(None)` may cite an actual empty XML leaf with its exact field and empty
  quote; a missing unobserved field is not converted into absence.
- Derived `line_count` requires the provenance method
  `count_unique_contiguous_line_ids`; unique accepted `line.<id>.*` keys must be
  contiguous from one, count/IDs/source locators must agree with provenance,
  and the evidence must still reference the original.

Image evidence requires an actual `PageImage` page/hash and nonempty transcribed
quotation; image quotation fidelity remains a manual/model-quality review, not
an automatic literal-text proof. Cached image hashes and locators are checked.
Resolution additionally verifies selected IDs, candidate attribute/value proofs,
source block/image proof and supplied hard constraints/exclusions.

Regeneration is explicit `record` work. Invalid or incompatible entries fail
without calling the provider; an absent successful capture or recorded prior
failure can be retried in record mode. Replay/fixture reproduce failure categories.
An unsuccessful regeneration does not destroy an older accepted capture.

## Stage runner, selection and resume

```python
from kalmora.documents.runner import StageRunner

runner = StageRunner('build/states', capture, resolver=recorded_resolver,
                     concurrency=2, landing=landing_store)
batch = await runner.run(parsed_documents_in_caller_order, phase=phase_name,
    stages=('extract', 'resolve'), request_builder=current_candidates,
    context={'master_version': master_version, 'prior_selection_version': version})
```

`request_builder(document, facts)` returns the current `ResolutionRequest`.
The runner adds extraction-result hash, phase and run-context hash, so changed
prior selection/state or accepted extraction invalidates resolution. The pure
`StageRunner.prepare_resolution` helper produces the identical request when
authoring semantic fixtures offline.

`selected_paths` restricts documents. `stages=('resolve',)` reads previously
accepted extraction only; it cannot implicitly call an omitted extraction stage.
`regenerate_paths` and `regenerate_stages` select an intersection to recapture in
explicit budgeted record mode. If only one selection is supplied, it applies to
all selected stages or documents respectively. Missing selections outside the
batch are errors; replay/fixture regeneration is forbidden.

An asynchronous semaphore bounds document work. Successful interpretation
envelopes are committed as they finish; returned results and landing writes
follow **caller input order**, independent of completion order. Landing calls
execute on the runner's owning PID/thread after work is collected. Repeated
identical facts rely on `LandingStore` idempotence; changed facts require a new
landing database/rebuild instead of silently replacing evidence.

State keys include phase, source/transformation, stage/input configuration and
run-context hashes. States record `RUNNING`, `ACCEPTED`, `FAILED`, `CANCELLED`
or `WRITE_FAILED`. They are diagnostics, never a second source of accepted facts:
resume always revalidates cached envelopes. Controlled cancellation persists
cancelled stage/run states; already accepted envelopes survive. Transient failed
record work retries on resume without duplicating earlier successful captures.
The runner has one owner and disallows overlapping batches.

The runner never writes ledger/accounting events and does not choose AP
chronology. The AP caller supplies its ordering/context and normally recomputes
policies, exact calculations, validation and output from returned typed results.
This preserves the chronology/receipt-consumption ownership of #46 and allows
the same staging layer to serve other modules later.

## Cost and reproducibility reports

The live client's `capture_cost_usd` covers **all attempts**, not only its final
response; `attempt_metrics` remains in the envelope. Unknown cost remains `None`
and visible in reports; it is never inferred from only final usage or treated
as zero. The live client's conservative unknown reservations remain active.
Replay/fixture report zero new provider calls and zero new provider cost,
separately from historical capture costs/origin. M0 `RunRecorder` can be supplied
to count cache hits; real attempts continue to be recorded by the live client,
not counted twice by recording wrappers.

`BatchResult.stable_sha256` fingerprints only source identities, accepted typed
results/statuses, unknowns and errors. Mode, capture/runtime cost, timing and cache-hit
metadata are excluded. Identical record/replay facts produce identical stable
hashes, while unknowns/contradictions remain in artifacts/envelopes. Accounting
output equality must additionally be checked by the accounting caller (#140);
this module has no fake accounting writer or golden lookup.

Offline validation:

```sh
PYTHONPATH=src python -m unittest discover -s tests -p test_document_replay.py -v
```

The tests exercise record/replay output equality, cancellation/resume, bounded
concurrency and owner-thread write order, no duplicated facts, selected document
regeneration, candidate/context invalidation, checksum and accepted-value
tampering, exact decimals, unknown historical cost, explicit XML absence and
derived count safeguards, image hashes, ambiguity/missing data, refusal,
invalid response, timeout/budget fixtures, and a subprocess with provider imports
and network connections forbidden and no API-key environment.
