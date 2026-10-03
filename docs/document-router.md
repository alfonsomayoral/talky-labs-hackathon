# Original document router (#39)

`DocumentRouter(phase_path).parse(relative_inbox_path)` returns a `ParsedDocument`.
`parse_folder(relative_inbox_directory)` returns every successfully read source
and a separate list of operational errors. Every attachment and message keeps
its own original SHA-256 and relative path; the router never decides AP outcomes.

The `documents` extra installs pinned pypdf/Pillow. Native PDFs retain page text
in layout mode, including table spacing and page breaks. Text-insufficient pages
carry `vision_required` and their embedded PNG/JPEG images. All three image-only
July AP PDFs have embedded images; interpretation happens in #137. A page with
neither usable text nor an embedded image raises an explicit error requiring a
renderer. No OCR weights or external parser services are downloaded.

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
