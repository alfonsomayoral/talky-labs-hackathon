# September document hardening (#222)

## Source-grounded design

Use native source structure before vision: deterministic XML, original PDF
layout/visitor fragments, conservative native tables, and original-page images
for scans or layouts that cannot be safely parsed. The model interprets headers
and ambiguous text; accounting remains outside this layer. Source instructions
are untrusted data. No organizer labels or golden enter extraction prompts.

This follows pypdf's [documented PDF extraction limits](https://github.com/py-pdf/pypdf/blob/main/docs/user/extract-text.md): PDF display order and semantic reading order can differ, and extracted text does not recover absent scanned text.
[OpenAI's document-understanding guidance](https://developers.openai.com/cookbook/examples/multimodal/document_and_multimodal_understanding_tips)
supports detailed image input, literal transcription and focused image crops.
Our crops retain exact parent pixels, hashes and coordinates. They add evidence
resolution without rewriting the document; their extra cost is measured.

[Tesseract's quality guidance](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html)
covers adequate resolution, skew, segmentation and difficult table structure.
Use OCR as an optional locator, never a vote that establishes the original text.
[OCRmyPDF](https://ocrmypdf.readthedocs.io/en/latest/cookbook.html) uses Tesseract;
wrapping the same engine does not provide independent corroboration. Cleaning
that changes content must not replace original evidence.

The open source runtime remains pypdf, Pillow, Poppler and optional Tesseract.
[Docling](https://github.com/docling-project/docling),
[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) and
[RapidOCR](https://github.com/RapidAI/RapidOCR) are primary-source alternatives,
not new dependencies. Adopting another parser requires measured improvement,
versioned source provenance and separate code/model-weight licensing checks.
There is no automatic weight download in production.

## Measured evidence, 2026-10-03

The original September archive contains 299 PDFs / 321 pages, 48 XML attachments,
329 JSON messages and three inbox CSVs. Four PDFs contain five scanned pages.
Dry inventory parsed all PDFs without operational errors. These are source
counts and extraction observations, not an official score.

The first Luna full-phase experiment completed 332/347 PDF/XML captures and
failed 15 (nine grounding, five schema, one field error). Independent source
review found four nominally successful invoices with no returned invoice rows,
despite 126 printed priced rows. A valid JSON response was insufficient.

The hardened native parser directly reads 1,140 invoice rows across 162 PDFs.
Twelve Portuguese invoices account for 62 actual invoice rows; the initial broad
candidate regex counted 73 and mixed in supplemental content. The source-based
recount supersedes that heuristic. Separate dated-hour parsing preserves the
parts of work instead of treating them as extra invoice charges. Unrecognized
or wrapped tables remain abstentions, not successful native parses.

Final offline assembly selected genuine captures for 347/347 original PDF/XML
attachments, with no uncited source pages. Native composition includes 193 dated
hour entries across 15 PDFs. Six wrapped native invoices were visually captured
and reviewed against their original renders. The assembly exposes unresolved
normalization/classification diagnostics rather than declaring them successful
accounting inputs. In particular ambiguous numeric date formats remain unresolved
unless the consuming layer supplies a justified date-order context.

One three-page, 96-row invoice now uses Luna for headers/footers and source code
for every row. Its measured fresh capture cost was USD 0.004427375; a 26-row
invoice cost USD 0.006220625. Original responses and every exploratory cost remain
archived. Some full-Sol native retries exceeded the USD 0.10 acceptance gate;
they are failed cost experiments, not approved benchmark results.

Independent visual review of four original scanned documents confirmed 16
invoice rows and eight supplemental entries, including quantities/prices/totals.
Sol initially read one customer name as `Kaimora`; original-pixel strips produced
`Kalmora`, confirmed against the source. Individual strip captures cost USD
0.0580375 and USD 0.0710200. A faint fiscal-validity footer remains explicitly
ambiguous. An invoice's 164 billed hours and its part's 44 recorded hours remain
separate observations; extraction does not invent missing hours or reconcile them.

The OCR comparison used six original rendered pages: installed English
`tessdata_fast` PSM 4 versus pinned official Spanish+English `tessdata_best/4.1.0`
PSM 4/6. Best data improved accents but still confused `IIa`/`IIIa` and roughly
doubled processing time. Token-overlap proxies were not exactness scores.
Consequently no new OCR model is promoted as factual authority.

## Remaining acceptance boundaries

Phase assembly reuses genuine captured responses and makes zero new provider
calls. Its coverage result must not be called a fresh live-model benchmark.
Literal native support does not establish semantic field assignment. Image
hashes identify evidence; independent original-image review establishes a
transcription, with unresolved text kept explicit.

The July held-out/semantic acceptance requirements of #222 remain separately
open. Freeze model/parser/prompt configuration before opening reserved labels;
do not tune on those answers. The original quality, completeness, grounding and
USD 0.10 per-document gates remain unchanged. The user removed provider/output
deadlines and authorized larger experimental budgets; actual latency, known
costs and unknown-cost reservations remain recorded. Luna remains the approved
provisional model, and Sol comparisons remain explicitly experimental.
