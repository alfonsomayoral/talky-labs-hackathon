# Original document router (#39)

`DocumentRouter(phase_path).parse(relative_inbox_path)` returns a `ParsedDocument`.
`parse_folder(relative_inbox_directory)` returns every successfully read source
and a separate list of operational errors. Every attachment and message keeps
its own original SHA-256 and relative path; the router never decides AP outcomes.

The `documents` extra installs pinned pypdf/Pillow. Native PDFs retain page text
in layout mode, including table spacing and page breaks. Text-insufficient pages
carry `page.N:vision_required` for subsequent whole-page rendering. Sparse text,
broken character maps, text-extraction errors and raster content also trigger
visual review. The router does not substitute embedded pictures for a complete
page: pictures omit surrounding text and vector content. A textless vector page
is retained for rendering. No OCR weights or external parser services are downloaded.

The `source-router-v3/pypdf-6.19.0` adapter additionally retains exact native
`visitor_text` callbacks as `page.N.fragment.K`, with page and source-field
locators. These fragments help cite separate columns and overprinted stamps when
layout text interleaves them. The original layout block is retained unchanged;
fragments are not reordered, joined or rewritten. Capture limits or failures
require visual review rather than silently claiming complete native evidence.

Facturae/CFDI XML retains namespace-independent indexed field/attribute paths
and original string values. Repeated elements and conflicting attachments are
not merged. Entity declarations and invalid XML are rejected. JSON messages are
validated while their text, including exact decimal spelling, remains intact.
DUA documents follow their actual PDF/XML format through the same adapters.

Document paths must be relative inbox sources within the active phase. Golden,
path traversal and escaped symlink targets are rejected. Unsupported, oversized,
missing, encrypted or damaged sources remain operational errors with source IDs;
they cannot become an invented accounting rejection/HOLD or successful fact.

Parsed source snapshots support JSON roundtrip with image hashes verified. The
transformation hash includes parser version, page/field text and image hashes.
Semantic-request fingerprints additionally include candidates and exact context,
so a changed vendor or available receipt quantity cannot reuse an old selection.

The initial adapter decision is documented in ADR0002. Optional future Docling
activation requires version/model-license review and the same source contracts.
