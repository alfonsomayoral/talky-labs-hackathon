# ADR 0002: document understanding and deterministic accounting

Status: implementation accepted; Luna release provisionally approved by the user.
Full model-quality acceptance is deferred to hotfix #222; measured failures remain visible.
Date: 2026-10-03. Scope: #134, #135–#140 and document adapters #39–#41.

## Problem and decision

AP has 305 July tasks. Originals include PDF tables, Facturae/CFDI XML,
notices, two-page PDFs and three image-only PDFs. The shared layer must interpret
these sources, preserve uncertainty and let developers rerun accounting without
paying for repeated model calls. Final accounting remains in the AP engines.

Use Python 3.12, PydanticAI with OpenAI Responses for typed interpretation,
explicit Python stages, and DuckDB as a reconstructible landing adapter. Use
pypdf for native PDF text with page provenance. Scanned pages can be rendered
with Poppler and receive unverified Tesseract locator text, followed by visual
interpretation against the rendered original. Structured XML is parsed directly
and keeps its own evidence. The model
receives only selected originals and bounded candidates from the active phase.
It has no filesystem, SQL, web, shell or golden tools.

| Option | Assessment | Decision |
| --- | --- | --- |
| PydanticAI with native structured output | Typed output and provider adaptation; actual attempts and raw responses require our explicit instrumentation. | One LLM framework. Disable implicit retries and tools. |
| OpenAI client with Pydantic | Small, viable implementation, with provider-specific control in application code. | Comparison baseline and transport dependency; avoid a second agent runtime. |
| LangGraph | Persistent graph execution useful for branching, long interruptions and human review. | Current stages have explicit state, bounded concurrency and no agent loops. Reconsider only if the workflow needs these features. |
| pypdf | Native page text and embedded images, with a small local runtime. | Initial PDF adapter; evaluate layout fidelity on the selected two-page/table cases. |
| Poppler/Tesseract | Optional bounded page rendering and OCR locator aids; source pixels remain authoritative. | Explicit CLI configuration, tool/weight hashes, no automatic downloads or OCR-as-fact. |
| Docling | Rich layout/OCR representation; requires additional runtime/model artifacts for its PDF pipeline. | Assessed alternative; no Docling weights loaded. |

## Reproducible dependencies and licensing

Exact direct dependency versions were checked in package metadata on this date.
Optional extras keep M0 and replay imports independent of provider libraries.

| Component | Version | Code license | Use |
| --- | --- | --- | --- |
| pydantic-ai-slim[openai] | 2.54.0 | MIT | `llm` extra; OpenAIResponsesModel and native JSON output. |
| pydantic | 2.13.5 | MIT | Strict model output validation. |
| openai | 3.24.0 | Apache-2.0 | Responses transport, automatic retries disabled. |
| pypdf | 6.19.0 | BSD-3-Clause | `documents` extra; PDF page text/images. |
| Pillow | 12.3.0 | MIT-CMU | PDF embedded-image decoding; no OCR weights. |
| duckdb | 1.5.5 | MIT | `landing` extra; embedded database, coordinated writer. |
| Docling | 2.132.0 | MIT | Assessed alternative; not an installed runtime dependency. |
| docling-ibm-models | 4.0.3 | MIT for code | Assessed companion package; no associated weights used. |
| Poppler `pdftoppm` | 26.05.0, conda-forge ARM64 build hd83632c_3 | GPL-2.0-or-later (installed package metadata) | Optional separate rendering executable; binary version/hash captured per run. |
| Tesseract | 5.5.0 | Apache-2.0 | Optional separate OCR executable; unverified aids only. |

Native PDF text and direct image input require no OCR weights. The optional
development OCR path uses `tessdata_fast/4.1.0/eng.traineddata`, Apache-2.0,
SHA-256 `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2`,
installed by the Homebrew formula from the upstream Tesseract repository.
Only `eng` is configured; Spanish/Portuguese weights are not silently installed.
The renderer's installed conda package SHA-256 is
`ef68570a8e06e890c1e800e4ce25fe6108b16d7482bdd2de6bf751b3be97183e`.
These native tools were exercised on macOS ARM64; Linux must supply explicit
compatible executables and language data, whose actual hashes enter provenance.
OpenAI models are commercial services, allowed by the user. A code package's
license does not establish downloadable weights' licensing. Record transitive versions
and licenses with each release's environment inventory. `requirements-m1.lock`
pins the initial runtime closure and `docs/dependencies-m1.json` records package
licenses/primary project URLs. CI installs this closure on Linux; direct pins
alone are not a complete dependency lock.

Python 3.12 on macOS ARM64 is the development target; CI uses Linux. PDF image
formats must be supported PNG/JPEG/WebP. Unsupported images, encrypted/broken
PDFs, missing optional libraries and XML errors produce explicit parse errors.
No automatic model-weight download or external OCR service is permitted.

## Contracts and ownership

`DocumentFacts`, `Fact` and `Evidence` remain the M0 boundary. Each attachment has
an independent source hash. Multiple values remain multiple facts; attachment
conflicts are preserved for deterministic normalization and policy evaluation.

| Contract | Meaning and owner |
| --- | --- |
| `ParsedBlock(id, text, page, source_field)` | Original page/XML-field text and stable locator. #39. |
| `PageImage(page, media_type, data)` | Embedded or original-page-rendered image bytes with content hash and explicit source page. Render transformation provenance is preserved. #39. |
| `ProcessingAid(page, text, provenance)` | Unverified OCR locator text and tool/configuration/weight/image/text hashes; never a source block or accepted fact. #39. |
| `ParsedDocument(path, source_sha256, media_type, parser_version, blocks, images, warnings, processing_aids)` | Relative original identity plus parsed representation and transformation hash including aids. #39/#137. |
| `DocumentExtractor.extract(ParsedDocument) -> DocumentFacts` | Asynchronous typed extraction. Same interface for real, recorded and synthetic responses. #137/#138. |
| `ResolutionRequest(document, candidates, context)` | Bounded candidates with stable IDs and relevant active-phase context. Candidate/context hash is part of recording identity. #137/#43. |
| `SemanticResolver.resolve(ResolutionRequest) -> ResolutionResult` | Asynchronous selection/abstention with evidence; selected IDs must belong to candidates. #137/#43. |
| `AsyncLLMClient.complete(output_type, instructions, prompt, images=())` | Typed output, original sanitized response and metadata; budget/time/retries instrumented. #135. |
| `LandingStore(path).import_phase(phase_path)` | Eight landing tables and read-only ERP/task adapter, original hashes, explicit parse errors and schema version. #136. |
| `LandingStore.store_facts(relative_path, facts)` | Store all observed/conflicting facts; populate normalized columns only when units and uniqueness are explicit. #136/#41. |
| Recording store / stage runner | Atomic successful result envelope, stage states, resume, mode and cache fingerprint. #138. |

Canonical observed fields include `supplier_tax_id`, `recipient_tax_id`,
`document_number`, `document_date`, `currency`, `document_type_hint`, `net`,
`tax`, `gross`, `iban`, `po_reference`, `receipt_reference`, and
`line.<id>.<field>`. Values preserve original text; monetary normalization happens
in code. Normalization retains individual `line.N.*` observations and evidence,
using explicit `*_cents`, `*_milli` and `*_e4` units where applicable; it does not
invent a different aggregate line contract.

Missing extraction is not an invented negative observation. A missing field
has no observed value. An explicit absence may be `Fact(None, evidence)` only
when supported by source content. Model confidence does not create evidence.
Text quotations must match the referenced source block. For image-only pages,
page/hash validation identifies the source; quotation fidelity needs source
review and the separate vision evaluation, and is not claimed as a deterministic
substring check. Short source-local image IDs select actual supplied bytes;
the caller retains their exact hash/page. Conflicting supplied identity fails.
Independent quotation reviews belong only to the evaluator and never enter
production prompts. OCR text/confidence cannot certify a quotation.

AP identity/order engines consume these facts and filtered candidates. Their
tax, arithmetic, duplicate, receipt, allocation, decision and posting policies
stay in code. The semantic result cannot create a master ID, confirm a receipt,
split quantities, choose a tax account or bypass a hard constraint.

## Execution modes

- `record`: call the provider explicitly, preserve raw response and accepted typed
  results, and record every actual attempt, usage, elapsed time and errors.
- `replay`: load only compatible recorded JSON; no provider initialization, API
  key or new call. Missing/incompatible recordings fail with stage/source detail.
- `fixture`: load identified synthetic doubles for unit cases, including missing
  fields, conflicts, refusals, invalid responses, timeouts and ambiguous choices.

All modes execute accounting engines and validators normally. Stage/document
selection allows regeneration of a chosen input without regenerating everything.
Replay proves integration and accounting on fixed facts; live evaluation proves
document understanding. Golden belongs only to evaluation. Expected fixture
outputs and evaluation annotations are never exposed as solver lookup tables.

Recording identity includes original hash, transformation/parser version, model,
provider, prompt version/content hash, schema version/hash and relevant settings.
Resolution also includes candidate and context hashes. Atomic recording commits
raw response and validated result together. Failure states are separate from
successful facts. Resumption and reuse cannot duplicate ledger events.

Parsing/extraction may run concurrently with a configured limit. DuckDB writes
have one coordinated process/thread owner. AP accounting follows the chronology
and receipt-consumption contracts supplied by the accounting agent.

## Model, limits and measurable acceptance

Initial candidate: `gpt-6-luna`, reasoning effort `low`, configurable. Astra is
excluded by the user. Documentation supports text/image and structured output;
quality on this package has not yet been established. A capability/schema match
does not close the quality issue.

Current configuration: no request deadline (user instruction, 2026-10-03), two attempts, concurrency two,
maximum 200,000 conservatively estimated input tokens, no application output-token limit (per subsequent user instruction), run budget
USD 5 (user-approved increase for model comparisons on 2026-10-03, with necessary
further extensions authorized and recorded explicitly).
Reserve an upper estimate before each real request; unknown usage retains
the conservative reservation. Auth/quota/refusal/schema/incomplete/network and
timeout failures remain distinct. SDK/agent automatic retries are disabled.
Request sizes, images and schema overhead must fit the input bound; no tools,
long context, Fast mode or regional-premium configuration is enabled implicitly.
Rates and their dated source are configurable; unknown cost remains visible.

The original-source sample is frozen in `docs/evaluation/ap-sample.json`: twelve
adjustment cases and eight reserved cases, covering tables, two-page input,
Facturae, CFDI/PDF disagreement, non-invoices, credit note, deposit request,
certification and image-only input. The sample describes original variants and
documents absent variants. Similar source templates recur: report this limitation
and all denominators, without claiming unseen-layout generalization.

These numeric criteria are fixed before any reserved-case model evaluation:

| Metric | Required threshold |
| --- | --- |
| Critical header/money/tax/line amount exactness | >= 95% of manually annotated present critical fields. |
| Required-field completeness | >= 95%, with missing and unsupported separated. |
| Grounded evidence location | 100%; image quotation fidelity checked against the original. |
| Fabricated values / out-of-candidate IDs | Zero accepted. |
| Semantic selection precision | 100% of selections against reviewed candidates. |
| Selection coverage on uniquely resolvable cases | >= 80%. |
| Correct abstention on ambiguous cases | 100%; distinguish synthetic variants from original cases. |
| Document latency | Report actual durations/p95; temporal gate removed by the user before holdout on 2026-10-03. |
| Estimated capture cost | <= USD 0.10/document; unknown cost fails this criterion. |

Evaluate per field, source, format and case; report numerator/denominator rather
than only a percentage. Separate extraction errors from policy/calculation and
serialization errors. Synthetic cases do not count as successful real held-out
cases. Freeze prompt/model configuration before the reserved run; a subsequent
change requires a newly identified evaluation, with the earlier result retained.

#139 closes only with measured results satisfying the fixed criteria, or an
explicitly accepted revision with consequences visible. #140 requires all 305
AP decisions, official contract/comparator integration, source/policy provenance,
golden absent from the solver, and identical accounting output from replay.

## Sources

- Original participant README, POLITICAS_CONTABLES §1–2, FORMATO_ENTREGA and
  active-phase ERP/tasks/inbox; no golden used to define extraction labels.
- [PydanticAI OpenAI adapter](https://pydantic.dev/docs/ai/models/openai/) and
  [native typed output](https://pydantic.dev/docs/ai/core-concepts/output/).
- [OpenAI structured output](https://developers.openai.com/api/docs/guides/structured-outputs),
  [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), and
  [pricing](https://developers.openai.com/api/docs/pricing), consulted 2026-10-03.
- [pypdf](https://pypdf.readthedocs.io/) and
  [Docling converter](https://docling-project.github.io/docling/reference/document_converter/).
- [Poppler](https://poppler.freedesktop.org/),
  [Tesseract](https://github.com/tesseract-ocr/tesseract), and
  [tessdata_fast 4.1.0 weights license](https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/LICENSE).
- [DuckDB concurrency](https://duckdb.org/docs/stable/connect/concurrency) and
  repository landing proposal/DDL, reviewed by the loader implementation.
