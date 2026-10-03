# Original phase document audit and capture

`tools/audit_phase_documents.py` inventories **every original inbox source** and
independently reads every PDF page with pypdf before the production router. It
is separate from the frozen July sample, labels, golden, evaluation and accounting
policy decisions. The report never declares a quality pass or an official score.

Dry inventory is the default and makes zero provider calls:

```sh
PYTHONPATH=src python tools/audit_phase_documents.py \
  --archive /path/kalmora_participant_test.zip \
  --extract-to /path/data/septiembre --output outputs/september-audit
```

The ZIP extractor validates all entry paths, types, encryption, duplicate names
and expanded sizes before writing. It rejects traversal, absolute paths,
symlinks and nonregular entries. Only `participant/phase_test/{inbox,tasks,erp}`
is extracted; the archive SHA-256 and every extracted file hash are recorded.
Existing identical extraction can be reused after rehashing; altered/incomplete
originals fail without replacement. Bank inputs are outside this extraction
allowlist. An existing phase can instead use `--phase-root /path/phase_test`.
Outputs must be separate from originals.

Each invocation has its own `runs/<uuid>/inventory.json`; failures remain in the
PDF denominator. The September inventory observed 299 PDFs, 321 pages, 21
multipage PDFs and four scanned PDFs with five image-only pages. The supplied
archive has no PDFs outside inbox. Its source SHA-256 is
`fe57cb9cc27ba66cf474ac91cdfcefde14766be25edb3f9280feae4105fc93f7`.
Those are source counts, not measured extraction accuracy.

Paid capture is an explicit additional operation:

```sh
PYTHONPATH=src python tools/audit_phase_documents.py \
  --phase-root /path/data/septiembre --output outputs/september-capture \
  --capture --model gpt-6-luna --budget 20 \
  --input-usd-per-million 0.125 --output-usd-per-million 0.50 \
  --pricing-provenance 'Caller-verified pricing source and date'
```

Prices must be verified by the caller; sample rates are not a provider bill.
Luna is the approved model; Sol options are explicitly experimental. Astra is
excluded. Provider request time and output tokens have no application cap. The
client still reserves bounded model capacity, audits every attempt, and retains
unknown-cost reservations. Local rendering/OCR keeps explicit operational guards
(configurable tool timeout, default 120 seconds per invocation).

Capture selects all PDF and XML attachments by default, including sources outside
AP. `--path inbox/...` can select a concrete original source for configuration
checks. XML uses `XMLDocumentExtractor` with zero provider calls. PDFs use the
existing router, `PDFVisionProcessor` for image-only pages, `LLMDocumentExtractor`,
normalization and classification. Default vision preparation renders original
pages without OCR. `--include-ocr-aids` enables unverified OCR in archives/prompts.
`--page-strips` adds the image evidence module's original overlapping page strips
after rendering and sets guarded input capacity to 900000 tokens. It requires
the matching image-contract implementation; native/full-page capture defaults
to 300000. `--max-input-tokens` selects a caller-verified capacity. This is an
input/spend guard, not a requested provider output limit.

Parsed documents are addressed by original/transformation SHA-256. Recording
stores are separated by exact model/prompt/schema/config identity. Normal resume
reuses compatible recorded captures after validation; `--fresh` recaptures and
preserves prior envelopes in recording history. Advisory per-key locks in the
recording store protect capture across concurrent workers. Unique run reports
and atomic document status files preserve completed work on interruption.

`capture.json` reports statuses/errors, unknowns, diagnostic fields/categories,
cost reservations, native/XML literal proofs, image observations requiring review,
and per-page source/image/citation coverage. A page with no accepted citation
remains visible. A successful extraction or exact native quote cannot establish
that every document field was captured. Image citations remain unverified until
independent original-image review. No accounting entries are generated.

The phase runner permits two validation attempts, requires page citations and
explicit row description states, and checks recognized native invoice row
coverage. A detected omitted table fails even if the header JSON is valid. Raw
responses from all repair attempts and their costs remain in recordings/reports.
Failed captures stay in the original denominator.

`--native-tables` enables deterministic invoice rows plus a separately recorded
`outside_native_invoice_table` model scope for headers, footers and other tables.
The full unchanged original is supplied. Composition is separate from recording;
every page must still have a final citation. `--render-all-pages` explicitly
prepares native pages too when their layout needs visual interpretation. Raw
capture and composed facts use different artifacts. Each document records its
exact configuration bundle; two configurations of the same source remain
distinguishable. One transport attempt per validation attempt bounds actual
model calls to two for an operation in this runner.

Offline assembly combines successful captures in the caller's explicit
precedence order and rechecks original hashes, parsed path/transformation,
literal evidence, page coverage and native row coverage:

```sh
PYTHONPATH=src python tools/assemble_phase_document_facts.py \
  --phase-root /path/data/septiembre --capture-root outputs/september-capture \
  --capture-root outputs/september-repairs --native-tables \
  --output outputs/september-assembled
```

The output manifest retains all original PDF/XML attachments, including failed
or uncaptured sources. Every fact file includes raw/normalized facts, uncertainty,
diagnostics, classification and exact capture lineage. Native projections are
explicit and retain superseded fields/unknowns in lineage. Assembly makes zero
provider calls and does not certify semantic labels or unreviewed image quotes.
It is distinct from the frozen original-source acceptance benchmark.

Focused offline validation:

```sh
PYTHONPATH=src python -m unittest discover -s tests -p test_phase_document_audit.py -v
```
