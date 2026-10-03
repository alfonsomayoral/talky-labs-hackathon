# AP source sample and frozen evaluation contract

The sample contains **20 original July AP tasks: 12 tuning and 8 holdout**. It supports #134 architecture decisions and the later #139 evaluation. No model has been called and no extraction score, cost or latency has been measured.

The exact task source is `phase_dev/tasks/ap_documents.json`, a JSON array of 305 document IDs. The external participant directory remains caller supplied; no source PDF, XML, message, ERP file or account identifier is copied into this repository. [ap-sample.json](ap-sample.json) records every selected relative path, complete SHA-256, format, page count and selection reason. Its frozen selection fingerprint is `02e51e54b38d39dc044b1afad85f3caf01d8140419aaf4629dacb378d1619d00`.

Selection used original AP messages, attachments, ERP masters/receipts and policy content. It did not consult golden, scoring output, `phase_test` or model results. IDs and filenames are source locators for the evaluator, never classification or matching rules for the solver. Document content is untrusted data, including any text resembling instructions.

## Frozen partition

| Alias | Original task | Split | Source structure and selection rationale |
|---|---|---|---|
| T01 | API004151 | tuning | One-page PDF; 18-row numeric table, decimal commas, PO and delivery-note references. |
| T02 | API004193 | tuning | Facturae 3.2.2 XML; nested totals and 17 repeated line nodes. |
| T03 | API005228 | tuning | PDF plus CFDI 4.0; two evidence-backed totals differ. |
| T04 | API005594 | tuning | Proposal-style PDF, small table and fiscal-validity disclaimer. |
| T05 | API005595 | tuning | Aging-style table with references, status, dates and a balance. |
| T06 | API005189 | tuning | Narrative notice with issue/effective dates and beneficiary change. |
| T07 | API005195 | tuning | Account-change letter, two dates and certificate/signature panels. |
| T08 | API005577 | tuning | Authority certificate, contractor identity and validity period. |
| T09 | API005584 | tuning | Negative signed amounts, correction reference and portal metadata. |
| T10 | API004469 | tuning | English deposit request also titled proforma; dollar symbol needs ERP currency context. |
| T11 | API004115 | tuning | Certification: cumulative/current amounts, retention and abbreviated `S/Ref.` label. |
| T12 | API005199 | tuning | Image-only invoice table; missing visible PO and historical delivery-reference collision. |
| H01 | API004232 | holdout | Two-page text-bearing PDF with a long transaction table. |
| H02 | API004283 | holdout | Independent XML-only document with repeated fields. |
| H03 | API004558 | holdout | PDF/CFDI pair with multiple monetary field families. |
| H04 | API005588 | holdout | Portuguese PDF with sign-sensitive numeric content. |
| H05 | API005592 | holdout | Short PDF with validity/disclaimer wording and tabular numbers. |
| H06 | API005597 | holdout | Independent table with date and status columns. |
| H07 | API005205 | holdout | Second image-only PDF in another language/document family. |
| H08 | API004483 | holdout | English PDF with foreign-currency notation and an ambiguous date format. |

H01 replaced the initially considered one-page API004177 before freezing and before any model evaluation. No tuning label, expected field value or expected semantic candidate for H01-H08 is included. Their manifest exposes source hashes and selection reasons only. The manifest itself is evaluator metadata and must not enter a solver/model prompt.

## Source coverage and limits

Across the AP task originals there are 262 PDFs and 58 XML attachments, plus 305 messages. PDF page counts are 246 one-page and 16 two-page documents. Exactly three PDFs lack a text layer: API005199, API005205 and API005209; all three were inspected visually. T12 and H07 cover genuine image-only documents. H01 covers page breaks; there is no PDF exceeding two pages in this task inventory.

Tax-garnishment wording was not found in task messages, text-bearing PDFs or XML, and none of the three image-only documents is a garnishment order. `TAX_GARNISHMENT_ORDER` is therefore an absent observed variant, requiring a separate clearly synthetic policy fixture later. A CFDI credit note whose XML carries positive magnitudes while the PDF displays negative amounts exists in the sources but is **present and unsampled**, not absent. The selected tuning labels cover eight of the nine policy document types. The single factoring-notice case is tuning only.

This is purposeful heterogeneous sampling, not a random estimate of July prevalence. The synthetic package repeats layout families across suppliers and splits. The sample measures held-out documents, not guaranteed unseen templates. A format containing one or two cases cannot support a broad statistical accuracy claim; all numerator/denominator pairs must remain visible. Duplicate source references can also recur across vendors and years, as T12 demonstrates. No exact selected attachment bytes are shared across splits.

## Manually reviewed tuning labels

[ap-tuning-annotations.json](../../fixtures/llm_eval/ap-tuning-annotations.json) contains 12 document-type labels and 102 individually identified facts. Each has an original source hash and a page/field location. PDF labels were checked against extracted text and rendered pages; T12 quotes are **manual image transcriptions**, with image-region/row locators. They are not claimed text-substring matches in an image-only PDF. XML facts name the original nodes or attributes, including the distinction between batch totals and invoice totals.

Monetary values are decimal strings in the document's currency major units; quantity strings retain their unit. Values are never passed through binary floats. The `state=absent` label is used only after inspecting the relevant original; an unlabelled field means unreviewed rather than absent, zero or null. Synthetic NIFs remain literal: the organizer expressly makes Spanish checksums invalid by design. Bank-account plaintext is excluded; selected labels measure presence and panel evidence only.

T03 has PDF gross `31691.90 MXN` and XML gross `32542.30 MXN`, with the same `27320.60` base and `4371.30` tax. Both are transcription targets. A combined total must remain unresolved; the extraction layer must not average or silently repair them. There is no accounting `REJECT` label in the sample. T10 prints `$ 44,400.00`; PO 4500022264 specifies USD. A dollar symbol alone is not labelled as a uniquely resolved currency. The PO has no explicit approval-state field, so the annotations do not invent approval or an accounting `POST` decision.

Line counts are complete for the labelled tables, but line-amount labels are selected first/last anchors. This fixture does **not** provide complete numeric ground truth for every table row. Full-table accuracy claims require additional original-source annotations before evaluation; anchor accuracy must be reported as anchor accuracy.

There are four manually unique semantic checks: three explicitly printed PO references, plus T12's final delivery reference resolved using the observed supplier and June 2026 context. `AL-057017` exists in two source GR rows: a historical row for another vendor and the applicable June 2026 row. It is ambiguous without contextual filters, and resolvable after them. The fixture does not claim that the complete original invoice is intrinsically ambiguous.

[ap-candidate-guard-variants.json](../../fixtures/llm_eval/ap-candidate-guard-variants.json) has two **explicitly synthetic context projections** for later unit validation: an intentionally context-free candidate query that must abstain, and a historical wrong-vendor/period candidate that must be rejected. Candidate IDs refer to real source records; the artificial part is the bounded query/context. These variants are not July held-out cases, must never enter its denominators, and have not been run against a model or implementation.

## Metrics and thresholds fixed before holdout

The parent fixed the following gates before any LLM run. They are recorded verbatim as numeric strings in the manifest. Candidate confidence is determined by evidence and deterministic candidate validity, not the model's self-reported confidence.

| Metric | Required gate | Denominator/reporting convention |
|---|---|---|
| Critical header, money, tax and selected line-amount exactness | >=95% | Tuning: 93 critical labelled values, including type and the explicitly listed headers; also report each field/family/format separately. Compare strings as exact Decimal values with the correct sign, currency and attachment. |
| Grounded evidence location | 100% | Tuning: 114 labelled values including types. Original hash plus correct page/node/field; quoted text fidelity or manual image grounding. Do not count an unsupported quote as grounded. |
| Fabricated values or IDs | 0 | Count all returned values/IDs; extra output is not ignored merely because it lacks an annotation. New IDs must belong to the supplied bounded candidate set. |
| Selected-candidate precision | 100% | Correct selected candidates / all selected candidates. An empty selection set is not a successful precision result; report it as undefined alongside coverage. |
| Unique resolvable-candidate coverage | >=80% | Tuning has 4 manually resolvable cases; 3/4 is 75%, so all four are needed to pass this small-N gate. |
| Correct abstention on ambiguous contexts | 100% | No intrinsically ambiguous complete original is labelled in tuning (N=0, report not applicable). Report the synthetic ambiguity guard separately (N=1), and T03's unresolved unified-total check separately (N=1). |
| Required-field completeness | >=95% per case | Required slots are that case's type plus enumerated facts; explicit absence must be represented coherently. Unreviewed fields are outside the denominator and cannot be claimed correct. |
| End-to-end capture latency p95 | <=60 seconds/document | Include retries and elapsed capture time, not just the fastest request. Nearest-rank p95 is the maximum for N=8 or N=12; include sample size and all case durations. |
| Estimated capture cost | <=0.10 USD/document | Include all paid attempts, image usage where available and caller-supplied pricing provenance. Unknown pricing/usage fails the cost gate. Never convert unknown usage to zero. |

Tuning per-format denominators are fixed in JSON:

| Attachment format | Labelled values including type | Critical values | Monetary values |
|---|---:|---:|---:|
| Text-bearing PDF | 84 | 67 | 25 |
| Facturae XML | 12 | 11 | 5 |
| CFDI XML | 4 | 4 | 3 |
| Image-only PDF | 14 | 11 | 5 |

All 38 monetary labels are a subset of the 93 critical labels; the 13 image facts exclude the separately counted image document-type label. One paired case contributes evidence to both PDF and XML format strata, while case-level metrics count it once. Per-field denominators must be derived from the exact fixture slots, without dropping misses or duplicates from the denominator.

Before the first holdout run, a separate evaluator must seal manual holdout annotations, their hash, field/format denominators and resolvability labels, using originals only. This commit intentionally contains no such answers. Freeze the prompt, model, extractor/schema/configuration versions and candidate-context construction before that run. Do not inspect holdout outputs to change a prompt or select a better attempt. A failed gate remains failed until a new explicitly versioned evaluation protocol and a fresh holdout are defined.

## Budget and reproducibility

The candidate is `gpt-6-luna`. The **smoke plus sample spend cap is 1.00 USD**, maximum 2 attempts/document, concurrency 2, output cap 8192 tokens and request timeout 60 seconds. The parent raised the previously considered 4096 output cap before evaluation to accommodate tables. The architecture ADR/client configuration owns these execution settings. There are currently **zero model calls**, no measured token counts and no pricing supplied by this sample.

The total spend cap is stricter than multiplying the per-document ceiling by 20. Reserve the estimated request cost against the remaining cap before each call and stop when it cannot be bounded. Retried attempts count toward both cost and elapsed time. Cache replay must record the hit and its original source/config/version; a cached answer does not erase the initial paid attempt. Record a run UUID, model/provider, request identifiers, UTC times, elapsed duration, token usage, prompt/config/source hashes, per-attempt errors and explicit pricing provenance. Never include API keys or credential-bearing headers in reports.

A future full AP run has 305 task documents. Estimate its budget from measured per-format input/image/output usage and the explicitly supplied price units: sum each format's document count times its measured cost, then add the declared retry allowance. Report the price source/date and assumptions. No full-AP budget or dollar estimate is asserted before those measurements and pricing exist. The 20-case sample cap does not authorize a full-AP run.

Reproduce source checks with Python standard-library JSON/SHA-256 against a caller-supplied participant directory. Use bundled Poppler `pdftotext -layout` for text-bearing PDFs and `pdftoppm` for visual review; use original XML node/attribute values. Hash the original bytes, not extracted text. Keep the original participant directory read-only. The manifest and both fixture JSON files have been checked for source-hash integrity, unique/disjoint case IDs, attachment-byte separation, tuning-only labels, exact Decimal strings and syntactic validity. These are artifact checks, not model evaluation or accounting-engine tests.

Public/anonymized copies should use T/H aliases, redact names/tax/bank identifiers and omit raw messages/document images. Maintain an evaluator-side alias-to-original-hash map; do not alter source bytes or pretend redacted images have the original file hash. The organizer declares this package synthetic, but this sample does not establish a policy for processing real customer documents.
