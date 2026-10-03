# Local PDF vision processing

`PDFVisionProcessor(phase_root, PDFVisionConfig()).process(parsed, artifact_dir)`
verifies the original inbox path/hash and renders only pages marked
`page.N:vision_required`. Default processing uses Poppler at 300 DPI and
Tesseract PSM 4, English. Tool paths and all limits are caller configurable;
missing tools/languages produce explicit `PDFVisionError.category` failures.
No dependency installation or network call is performed.

Install the optional Python `documents` extra and provide the open source CLI
tools on `PATH` (macOS: `brew install poppler tesseract`; Debian/Ubuntu:
`apt-get install poppler-utils tesseract-ocr`). An explicit tool path is supported
when the application supplies a bundled runtime. Language packs must exist for
the configured language; the processor does not silently change languages.

Original blocks, bytes and source hash remain intact. Full rendered PNGs replace
embedded images on those pages. `processing_aids` contain OCR text and provenance,
never authoritative blocks. `unverified_ocr` warnings require original-image
review: OCR errors in amounts, dates and IBANs occur even with high confidence.
A matching OCR quote proves transcription provenance, not original-source fidelity.

Source size (20 MB), page count (4), page pixels (12 million), rendered image
size (10 MB), text/TSV size (2 MB each), subprocess output and timeout (30 seconds
per invocation) are bounded. Page dimensions are checked before rendering.
Processes receive explicit argument arrays, no shell, and one OCR thread.
Limits apply per page/invocation; the maximum process count follows the page cap.

Artifact destinations must be outside originals. Optional atomic artifacts are
`<source SHA>/page-N/render.png`, `ocr.txt`, `ocr.tsv`, and `metadata.json`.
Provenance captures original/image/text/TSV hashes, tool versions/binary hashes,
config, and available trained-data hashes. A processing fingerprint updates the
parser/transformation identity, invalidating incompatible recordings. English is
currently installed; Spanish/Portuguese are not inferred or silently substituted.

`LLMConfig.image_detail` supports `auto`, `low` and `high`; it is part of the
recording identity and is forwarded to the Responses image input. The sample
capturer uses `high` for document inspection. Output length remains unlimited
by the application unless a caller explicitly requests a limit; spend accounting
and operational bounds remain independent.

Tools are discovered through `PATH`; callers can supply explicit executable paths.
Missing tools fail only when vision-required processing is needed. Documents with
existing processing aids are rejected as `already_processed`, preventing duplicate
OCR aids and unstable repeated transformation identities.
